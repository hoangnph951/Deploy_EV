"""Availability, downtime, and fault-recovery measurement for a local API."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field


class AvailabilitySample(BaseModel):
    """One timestamped functional probe."""

    model_config = ConfigDict(extra="forbid")

    offset_seconds: float = Field(ge=0)
    observed_at: datetime
    phase: str
    available: bool
    status_code: int | None = None
    outcome: str | None = None
    latency_ms: float = Field(ge=0)
    error: str | None = None


class ErrorWindow(BaseModel):
    """A contiguous series of unavailable probes ending at first recovery."""

    model_config = ConfigDict(extra="forbid")

    started_offset_seconds: float
    recovered_offset_seconds: float | None
    downtime_seconds: float = Field(ge=0)
    failure_count: int = Field(ge=1)
    first_error: str | None = None


class AvailabilitySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_count: int
    available_count: int
    unavailable_count: int
    availability_percent: float
    error_windows: list[ErrorWindow]
    total_downtime_seconds: float
    longest_downtime_seconds: float
    mttr_seconds: float | None
    duration_seconds: float
    limitation: str = "Local single-instance availability; not a production HA/SLO claim."


def _functional_availability(status_code: int | None, outcome: str | None) -> bool:
    """Typed degradation remains available when HTTP and contract are valid."""

    if status_code is None or not (200 <= status_code < 300):
        return False
    return outcome in {
        "OK",
        "FEASIBLE",
        "SAFE_FALLBACK",
        "INSUFFICIENT_EVIDENCE",
    }


def calculate_error_windows(
    samples: list[AvailabilitySample],
    *,
    end_offset_seconds: float | None = None,
) -> list[ErrorWindow]:
    """Merge contiguous failures and close them at the first successful probe."""

    ordered = sorted(samples, key=lambda sample: sample.offset_seconds)
    windows: list[ErrorWindow] = []
    start: AvailabilitySample | None = None
    failures: list[AvailabilitySample] = []
    for sample in ordered:
        if not sample.available:
            if start is None:
                start = sample
                failures = []
            failures.append(sample)
            continue
        if start is not None:
            windows.append(
                ErrorWindow(
                    started_offset_seconds=start.offset_seconds,
                    recovered_offset_seconds=sample.offset_seconds,
                    downtime_seconds=max(
                        0.0, sample.offset_seconds - start.offset_seconds
                    ),
                    failure_count=len(failures),
                    first_error=start.error or start.outcome,
                )
            )
            start = None
            failures = []
    if start is not None:
        final_offset = (
            end_offset_seconds
            if end_offset_seconds is not None
            else (ordered[-1].offset_seconds if ordered else start.offset_seconds)
        )
        windows.append(
            ErrorWindow(
                started_offset_seconds=start.offset_seconds,
                recovered_offset_seconds=None,
                downtime_seconds=max(0.0, final_offset - start.offset_seconds),
                failure_count=len(failures),
                first_error=start.error or start.outcome,
            )
        )
    return windows


def summarize_availability(
    samples: list[AvailabilitySample], *, duration_seconds: float
) -> AvailabilitySummary:
    if not samples:
        raise ValueError("Availability soak produced no samples")
    windows = calculate_error_windows(
        samples, end_offset_seconds=duration_seconds
    )
    available_count = sum(sample.available for sample in samples)
    closed = [window.downtime_seconds for window in windows if window.recovered_offset_seconds is not None]
    downtimes = [window.downtime_seconds for window in windows]
    return AvailabilitySummary(
        sample_count=len(samples),
        available_count=available_count,
        unavailable_count=len(samples) - available_count,
        availability_percent=available_count / len(samples) * 100,
        error_windows=windows,
        total_downtime_seconds=sum(downtimes),
        longest_downtime_seconds=max(downtimes, default=0.0),
        mttr_seconds=sum(closed) / len(closed) if closed else None,
        duration_seconds=duration_seconds,
    )


class LocalApiProcess:
    """Own an isolated Uvicorn child used only by the evaluation run."""

    def __init__(
        self,
        *,
        run_directory: Path,
        port: int,
        supervisor_mode: Literal["live", "fallback", "timeout"] = "fallback",
        interpreter: Path | None = None,
    ):
        resolved = run_directory.resolve()
        workspace = Path.cwd().resolve()
        if resolved == workspace or workspace not in resolved.parents:
            raise ValueError("Evaluation run directory must be inside the workspace")
        resolved.mkdir(parents=True, exist_ok=True)
        self.run_directory = resolved
        self.port = port
        self.supervisor_mode = supervisor_mode
        self.interpreter = (interpreter or Path(sys.executable)).resolve()
        self.base_url = f"http://127.0.0.1:{port}"
        self._process: asyncio.subprocess.Process | None = None
        self._stdout_handle = None
        self._stderr_handle = None

    async def start(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        database_path = (self.run_directory / "availability.db").resolve()
        environment = os.environ.copy()
        environment.update(
            {
                "APP_ENV": "test",
                "EVALUATION_DATABASE_PATH": str(database_path),
                "EVALUATION_SUPERVISOR_MODE": self.supervisor_mode,
                "SIMULATOR_FAULT_INJECTION_ENABLED": "true",
            }
        )
        self._stdout_handle = (self.run_directory / "api.stdout.log").open(
            "ab"
        )
        self._stderr_handle = (self.run_directory / "api.stderr.log").open(
            "ab"
        )
        self._process = await asyncio.create_subprocess_exec(
            str(self.interpreter),
            "-m",
            "uvicorn",
            "eval.local_app:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
            env=environment,
            stdout=self._stdout_handle,
            stderr=self._stderr_handle,
        )

    async def wait_ready(self, timeout_seconds: float) -> float:
        started = time.perf_counter()
        deadline = started + timeout_seconds
        async with httpx.AsyncClient(timeout=1) as client:
            while time.perf_counter() < deadline:
                if self._process is not None and self._process.returncode is not None:
                    raise RuntimeError(
                        f"Local API exited during startup with code {self._process.returncode}"
                    )
                try:
                    response = await client.get(f"{self.base_url}/health")
                    if response.status_code == 200:
                        return time.perf_counter() - started
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.05)
        raise TimeoutError("Local API did not become ready before timeout")

    async def restart(self) -> None:
        await self.stop()
        await self.start()

    async def stop(self) -> None:
        process = self._process
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except TimeoutError:
                process.kill()
                await process.wait()
        self._process = None
        for handle_name in ("_stdout_handle", "_stderr_handle"):
            handle = getattr(self, handle_name)
            if handle is not None:
                handle.close()
                setattr(self, handle_name, None)

    async def set_fault(self, fault: str) -> None:
        async with httpx.AsyncClient(timeout=2) as client:
            response = await client.post(
                f"{self.base_url}/evaluation/fault", json={"fault": fault}
            )
            response.raise_for_status()

    async def probe(self) -> tuple[int | None, str | None, str | None]:
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                response = await client.get(f"{self.base_url}/evaluation/probe")
            outcome = None
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    outcome = payload.get("outcome")
            except ValueError:
                outcome = "INVALID_CONTRACT"
            return response.status_code, outcome, None
        except httpx.TimeoutException:
            return None, "TIMEOUT", "TIMEOUT"
        except httpx.HTTPError as exc:
            return None, "CONNECTION_ERROR", type(exc).__name__


async def _maybe_call(process: Any, method: str, *args: Any) -> None:
    operation = getattr(process, method, None)
    if operation is None:
        raise RuntimeError(f"Availability process does not implement {method}")
    await operation(*args)


async def run_availability_soak(
    process: LocalApiProcess,
    *,
    duration_seconds: int = 600,
    request_interval_seconds: float = 1.0,
    _clock: Any = time.perf_counter,
    _sleep: Any = asyncio.sleep,
) -> tuple[list[AvailabilitySample], AvailabilitySummary]:
    """Measure functional availability across degradation and restart faults."""

    if duration_seconds <= 0 or request_interval_seconds <= 0:
        raise ValueError("Soak duration and request interval must be positive")
    samples: list[AvailabilitySample] = []
    applied: set[str] = set()
    try:
        await process.start()
        await process.wait_ready(timeout_seconds=30)
        started = _clock()
        while True:
            offset = _clock() - started
            if offset >= duration_seconds:
                break
            ratio = offset / duration_seconds
            phase = "BASELINE"
            if ratio >= 0.75:
                phase = "POST_RESTART"
                if "restart" not in applied:
                    await _maybe_call(process, "set_fault", "NONE")
                    # Observe a real connection failure while the single API
                    # instance is down, then recover on a later probe.
                    await process.stop()
                    failure_started = _clock()
                    down_status, down_outcome, down_error = await process.probe()
                    samples.append(
                        AvailabilitySample(
                            offset_seconds=failure_started - started,
                            observed_at=datetime.now(UTC),
                            phase="FORCED_RESTART",
                            available=_functional_availability(
                                down_status, down_outcome
                            ),
                            status_code=down_status,
                            outcome=down_outcome,
                            latency_ms=max(0.0, (_clock() - failure_started) * 1000),
                            error=down_error,
                        )
                    )
                    if samples[-1].available:
                        raise RuntimeError(
                            "Forced restart did not produce connection downtime"
                        )
                    await process.start()
                    applied.add("restart")
            elif ratio >= 0.55:
                phase = "F1_PROVIDER_FAILURE"
                if "provider" not in applied:
                    await _maybe_call(process, "set_fault", "NONE")
                    await _maybe_call(process, "set_fault", "F1_PROVIDER_FAILURE")
                    applied.add("provider")
            elif ratio >= 0.35:
                phase = "LLM_TIMEOUT"
                if "timeout" not in applied:
                    await _maybe_call(process, "set_fault", "LLM_TIMEOUT")
                    applied.add("timeout")

            probe_started = _clock()
            status_code, outcome, error = await process.probe()
            latency_ms = max(0.0, (_clock() - probe_started) * 1000)
            samples.append(
                AvailabilitySample(
                    offset_seconds=offset,
                    observed_at=datetime.now(UTC),
                    phase=phase,
                    available=_functional_availability(status_code, outcome),
                    status_code=status_code,
                    outcome=outcome,
                    latency_ms=latency_ms,
                    error=error,
                )
            )
            remaining = request_interval_seconds - (_clock() - probe_started)
            if remaining > 0:
                await _sleep(remaining)
    finally:
        await process.stop()
    return samples, summarize_availability(samples, duration_seconds=duration_seconds)
