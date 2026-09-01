"""Bounded asynchronous HTTP workloads for the local F3/F4 benchmark."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field

from eval.metrics import percentile


class WorkloadSpec(BaseModel):
    """A reproducible workload at one concurrency level."""

    model_config = ConfigDict(extra="forbid")

    name: Literal["F3_TICK", "F4_DETERMINISTIC", "F4_LIVE_LLM"]
    concurrency: int = Field(ge=1)
    samples: int = Field(ge=1)
    warmup_samples: int = Field(ge=0)
    timeout_seconds: float = Field(gt=0)


class RequestSpec(BaseModel):
    """One request generated without sharing idempotency identifiers."""

    model_config = ConfigDict(extra="forbid")

    method: str = "POST"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    json_body: dict[str, Any] | None = None


class RequestFactory(Protocol):
    """Create the request for a unique workload sequence number."""

    def __call__(self, sequence: int) -> RequestSpec | Awaitable[RequestSpec]: ...


class LatencySample(BaseModel):
    """Raw evidence for one measured HTTP request."""

    model_config = ConfigDict(extra="forbid")

    workload: str
    concurrency: int
    sequence: int
    status_code: int | None
    latency_ms: float = Field(ge=0)
    started_offset_ms: float = Field(ge=0)
    finished_offset_ms: float = Field(ge=0)
    error: str | None = None
    tool_latency_ms: float | None = Field(default=None, ge=0)
    model: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)


class ProcessSample(BaseModel):
    """CPU/RSS sample for the managed API process and all its children."""

    model_config = ConfigDict(extra="forbid")

    offset_seconds: float = Field(ge=0)
    cpu_percent: float = Field(ge=0)
    rss_bytes: int = Field(ge=0)


class PricingSnapshot(BaseModel):
    """Versioned pricing input; never infer cost without one."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1)
    version: str = Field(min_length=1)
    input_usd_per_million_tokens: float = Field(ge=0)
    output_usd_per_million_tokens: float = Field(ge=0)


class ProcessSampler:
    """Fixed-interval process sampler that fails preflight when unsupported."""

    def __init__(self, pid: int, *, interval_seconds: float = 0.5):
        if interval_seconds <= 0:
            raise ValueError("Process sample interval must be positive")
        try:
            import psutil  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "psutil is required for benchmark CPU/RSS sampling"
            ) from exc
        try:
            self._psutil = psutil
            self._process = psutil.Process(pid)
            self._process.cpu_percent(None)
            for child in self._process.children(recursive=True):
                child.cpu_percent(None)
        except Exception as exc:
            raise RuntimeError(
                f"Unable to initialize process sampling for API pid {pid}"
            ) from exc
        self.interval_seconds = interval_seconds
        self.samples: list[ProcessSample] = []
        self._stop = asyncio.Event()

    def sample_once(self, started_ns: int) -> ProcessSample:
        processes = [self._process, *self._process.children(recursive=True)]
        cpu_percent = 0.0
        rss_bytes = 0
        live_processes = 0
        for process in processes:
            try:
                cpu_percent += max(0.0, process.cpu_percent(None))
                rss_bytes += max(0, process.memory_info().rss)
                live_processes += 1
            except (self._psutil.NoSuchProcess, self._psutil.AccessDenied):
                continue
        if live_processes == 0:
            raise RuntimeError("Managed API process exited during resource sampling")
        sample = ProcessSample(
            offset_seconds=(time.perf_counter_ns() - started_ns) / 1_000_000_000,
            cpu_percent=cpu_percent,
            rss_bytes=rss_bytes,
        )
        self.samples.append(sample)
        return sample

    async def run(self) -> list[ProcessSample]:
        started_ns = time.perf_counter_ns()
        while not self._stop.is_set():
            self.sample_once(started_ns)
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.interval_seconds
                )
            except TimeoutError:
                pass
        return self.samples

    def stop(self) -> None:
        self._stop.set()


def summarize_process_samples(samples: list[ProcessSample]) -> dict[str, Any]:
    """Calculate peak resources and a conservative RSS growth signal."""

    if not samples:
        raise ValueError("Process sampling produced no samples")
    xs = [sample.offset_seconds for sample in samples]
    ys = [float(sample.rss_bytes) for sample in samples]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    denominator = sum((value - x_mean) ** 2 for value in xs)
    slope = (
        sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True))
        / denominator
        if denominator > 0
        else 0.0
    )
    # A positive slope alone can be allocator warm-up. Mark instability only
    # when growth exceeds both 1 MiB/min and 5% of starting RSS per minute.
    slope_per_minute = slope * 60
    threshold = max(1024 * 1024, ys[0] * 0.05)
    return {
        "sample_count": len(samples),
        "max_cpu_percent": max(sample.cpu_percent for sample in samples),
        "max_rss_bytes": max(sample.rss_bytes for sample in samples),
        "memory_slope_bytes_per_minute": slope_per_minute,
        "memory_slope_unstable": slope_per_minute > threshold,
        "cpu_over_85_fraction": sum(
            sample.cpu_percent > 85 for sample in samples
        )
        / len(samples),
        "cpu_sustained_over_85": (
            len(samples) >= 3
            and sum(sample.cpu_percent > 85 for sample in samples) / len(samples)
            >= 0.5
        ),
    }


def _error_name(exc: BaseException) -> str:
    """Store a stable error class without leaking request/provider payloads."""

    if isinstance(exc, TimeoutError | httpx.TimeoutException):
        return "TIMEOUT"
    return type(exc).__name__


async def _make_request(
    factory: RequestFactory,
    client: httpx.AsyncClient,
    sequence: int,
    timeout_seconds: float,
) -> tuple[int | None, str | None, float | None, dict[str, Any]]:
    produced = factory(sequence)
    request = await produced if isinstance(produced, Awaitable) else produced
    try:
        async with asyncio.timeout(timeout_seconds):
            response = await client.request(
                request.method,
                request.url,
                headers=request.headers,
                json=request.json_body,
            )
        metadata: dict[str, Any] = {}
        try:
            payload = response.json()
            if isinstance(payload, dict):
                metadata = payload.get("evaluation", {}) or {}
        except ValueError:
            metadata = {}
        tool_latency = metadata.get("tool_latency_ms")
        return response.status_code, None, tool_latency, metadata
    except Exception as exc:  # each failed request is evidence, not a runner failure
        return None, _error_name(exc), None, {}


async def run_workload(
    base_url: str,
    spec: WorkloadSpec,
    factory: RequestFactory,
) -> list[LatencySample]:
    """Run warm-up then measured requests through a bounded worker pool."""

    samples: list[LatencySample] = []
    run_started = time.perf_counter_ns()
    client_timeout = httpx.Timeout(spec.timeout_seconds)

    async with httpx.AsyncClient(base_url=base_url, timeout=client_timeout) as client:
        async def run_phase(
            sequences: list[int], *, measured: bool
        ) -> None:
            queue: asyncio.Queue[int | None] = asyncio.Queue()
            for sequence in sequences:
                queue.put_nowait(sequence)
            for _ in range(spec.concurrency):
                queue.put_nowait(None)

            async def worker() -> None:
                while True:
                    sequence = await queue.get()
                    try:
                        if sequence is None:
                            return
                        started = time.perf_counter_ns()
                        status, error, tool_latency, metadata = await _make_request(
                            factory, client, sequence, spec.timeout_seconds
                        )
                        finished = time.perf_counter_ns()
                        if measured:
                            samples.append(
                                LatencySample(
                                    workload=spec.name,
                                    concurrency=spec.concurrency,
                                    sequence=sequence - spec.warmup_samples,
                                    status_code=status,
                                    latency_ms=(finished - started) / 1_000_000,
                                    started_offset_ms=(started - run_started) / 1_000_000,
                                    finished_offset_ms=(finished - run_started) / 1_000_000,
                                    error=error,
                                    tool_latency_ms=tool_latency,
                                    model=metadata.get("model"),
                                    input_tokens=metadata.get("input_tokens"),
                                    output_tokens=metadata.get("output_tokens"),
                                    estimated_cost_usd=None,
                                )
                            )
                    finally:
                        queue.task_done()

            workers = [
                asyncio.create_task(worker()) for _ in range(spec.concurrency)
            ]
            await queue.join()
            await asyncio.gather(*workers)

        # Warm-up is a distinct completed phase so it cannot overlap measured
        # requests at CCU > 1.
        if spec.warmup_samples:
            await run_phase(list(range(spec.warmup_samples)), measured=False)
        await run_phase(
            list(range(spec.warmup_samples, spec.warmup_samples + spec.samples)),
            measured=True,
        )

    return sorted(samples, key=lambda sample: sample.sequence)


def summarize_workload(
    samples: list[LatencySample], baseline_p95_ms: float | None
) -> dict[str, Any]:
    """Summarize raw samples without manufacturing unavailable process metrics."""

    if not samples:
        raise ValueError("Cannot summarize an empty workload")
    latencies = [sample.latency_ms for sample in samples]
    failures = [
        sample
        for sample in samples
        if sample.error is not None
        or sample.status_code is None
        or sample.status_code >= 400
    ]
    elapsed_ms = max(sample.finished_offset_ms for sample in samples) - min(
        sample.started_offset_ms for sample in samples
    )
    p95_ms = percentile(latencies, 0.95)
    error_rate = len(failures) / len(samples)
    latency_saturated = (
        baseline_p95_ms is not None
        and baseline_p95_ms > 0
        and p95_ms > baseline_p95_ms * 2
    )
    return {
        "workload": samples[0].workload,
        "concurrency": samples[0].concurrency,
        "sample_count": len(samples),
        "p50_ms": percentile(latencies, 0.50),
        "p95_ms": p95_ms,
        "p99_ms": percentile(latencies, 0.99),
        "throughput_rps": len(samples) / (elapsed_ms / 1000) if elapsed_ms > 0 else None,
        "error_count": len(failures),
        "error_rate": error_rate,
        "baseline_p95_ms": baseline_p95_ms,
        "saturation_reasons": [
            reason
            for condition, reason in (
                (error_rate > 0.01, "ERROR_RATE_GT_1_PERCENT"),
                (latency_saturated, "P95_GT_2X_CCU1"),
            )
            if condition
        ],
    }


def first_saturation_level(summaries: list[dict[str, Any]]) -> int | None:
    """Return the first CCU with any observed saturation signal."""

    ordered = sorted(summaries, key=lambda summary: int(summary["concurrency"]))
    for summary in ordered:
        if summary.get("saturation_reasons"):
            return int(summary["concurrency"])
        if summary.get("cpu_sustained_over_85") is True:
            return int(summary["concurrency"])
        if summary.get("memory_slope_unstable") is True:
            return int(summary["concurrency"])
    return None


def build_default_factories() -> dict[str, RequestFactory]:
    """Default factories for local HTTP performance matrix endpoints."""

    def f3_factory(sequence: int) -> RequestSpec:
        return RequestSpec(method="GET", url="/api/v1/monitoring/capabilities")

    def f4_factory(sequence: int) -> RequestSpec:
        return RequestSpec(
            method="POST",
            url=f"/api/v1/trips/load-trip-{sequence}/replans",
            json_body={"event_type": "TRAFFIC_JAM", "severity": 0.8},
        )

    return {
        "F3_TICK": f3_factory,
        "F4_DETERMINISTIC": f4_factory,
        "F4_LIVE_LLM": f4_factory,
    }


async def run_performance_matrix(
    base_url: str,
    manifest: Any,
    factories: dict[str, RequestFactory] | None = None,
    *,
    process_pid: int | None = None,
    pricing_snapshot: PricingSnapshot | None = None,
) -> tuple[list[LatencySample], dict[str, Any]]:
    """Run the plan's exact deterministic matrix and optional live-LLM slice."""

    if factories is None:
        factories = build_default_factories()
    all_samples: list[LatencySample] = []
    summaries: list[dict[str, Any]] = []
    matrix = [
        *(WorkloadSpec(name="F3_TICK", concurrency=ccu, samples=200, warmup_samples=10, timeout_seconds=10) for ccu in (1, 5, 10, 20)),
        *(WorkloadSpec(name="F4_DETERMINISTIC", concurrency=ccu, samples=40, warmup_samples=3, timeout_seconds=30) for ccu in (1, 5, 10, 20)),
    ]
    provider_modes = getattr(manifest, "provider_modes", {})
    if provider_modes.get("supervisor") == "live":
        matrix.append(
            WorkloadSpec(
                name="F4_LIVE_LLM",
                concurrency=1,
                samples=10,
                warmup_samples=1,
                timeout_seconds=60,
            )
        )

    baselines: dict[str, float] = {}
    for spec in matrix:
        factory = factories.get(spec.name)
        if factory is None:
            raise ValueError(f"Missing request factory for {spec.name}")
        sampler = ProcessSampler(process_pid) if process_pid is not None else None
        sampler_task = asyncio.create_task(sampler.run()) if sampler else None
        try:
            samples = await run_workload(base_url, spec, factory)
        finally:
            if sampler is not None:
                sampler.stop()
            process_samples = await sampler_task if sampler_task else []
        if spec.name == "F4_LIVE_LLM" and pricing_snapshot is not None:
            for sample in samples:
                if sample.input_tokens is not None and sample.output_tokens is not None:
                    sample.estimated_cost_usd = (
                        sample.input_tokens
                        * pricing_snapshot.input_usd_per_million_tokens
                        + sample.output_tokens
                        * pricing_snapshot.output_usd_per_million_tokens
                    ) / 1_000_000
        summary = summarize_workload(samples, baselines.get(spec.name))
        if process_samples:
            summary.update(summarize_process_samples(process_samples))
        if spec.concurrency == 1:
            baselines[spec.name] = float(summary["p95_ms"])
            summary["baseline_p95_ms"] = summary["p95_ms"]
        all_samples.extend(samples)
        summaries.append(summary)

    return all_samples, {
        "workloads": summaries,
        "first_saturation_ccu": {
            name: first_saturation_level(
                [summary for summary in summaries if summary["workload"] == name]
            )
            for name in sorted({summary["workload"] for summary in summaries})
        },
        "limitations": [
            *(
                []
                if process_pid is not None
                else ["CPU/RSS sampling was not requested for this matrix."]
            ),
            "Token and cost fields remain null when the provider does not return them.",
        ],
        "pricing_snapshot": (
            pricing_snapshot.model_dump(mode="json") if pricing_snapshot else None
        ),
    }


def required_audit_sample_count(record_count: int, rate: float = 0.20) -> int:
    """Shared exact rounding rule used by performance/report tests."""

    return math.ceil(record_count * rate)
