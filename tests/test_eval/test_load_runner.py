import asyncio

import pytest

from eval.load_runner import (
    LatencySample,
    ProcessSample,
    RequestSpec,
    WorkloadSpec,
    first_saturation_level,
    run_workload,
    summarize_process_samples,
    summarize_workload,
)


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _RecordingClient:
    in_flight = 0
    max_in_flight = 0
    calls = []
    delay = 0.005
    completed = []
    measured_started_before_warmup_finished = False

    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def request(self, method, url, **_kwargs):
        type(self).calls.append((method, url))
        sequence = int(url.rsplit("/", 1)[-1]) if url.rsplit("/", 1)[-1].isdigit() else None
        if sequence is not None and sequence >= 4 and len(type(self).completed) < 4:
            type(self).measured_started_before_warmup_finished = True
        type(self).in_flight += 1
        type(self).max_in_flight = max(
            type(self).max_in_flight, type(self).in_flight
        )
        try:
            await asyncio.sleep(type(self).delay)
            return _FakeResponse(
                payload={"evaluation": {"tool_latency_ms": 1.25}}
            )
        finally:
            type(self).in_flight -= 1
            type(self).completed.append(url)


@pytest.fixture(autouse=True)
def reset_client():
    _RecordingClient.in_flight = 0
    _RecordingClient.max_in_flight = 0
    _RecordingClient.calls = []
    _RecordingClient.delay = 0.005
    _RecordingClient.completed = []
    _RecordingClient.measured_started_before_warmup_finished = False


@pytest.mark.asyncio
async def test_worker_pool_is_bounded_and_excludes_warmup(monkeypatch):
    monkeypatch.setattr("eval.load_runner.httpx.AsyncClient", _RecordingClient)
    spec = WorkloadSpec(
        name="F3_TICK",
        concurrency=3,
        samples=8,
        warmup_samples=4,
        timeout_seconds=1,
    )

    samples = await run_workload(
        "http://local",
        spec,
        lambda sequence: RequestSpec(url=f"/probe/{sequence}"),
    )

    assert len(_RecordingClient.calls) == 12
    assert len(samples) == 8
    assert [sample.sequence for sample in samples] == list(range(8))
    assert _RecordingClient.max_in_flight == 3
    assert _RecordingClient.measured_started_before_warmup_finished is False
    assert all(sample.status_code == 200 for sample in samples)
    assert all(sample.error is None for sample in samples)
    assert all(sample.tool_latency_ms == 1.25 for sample in samples)


@pytest.mark.asyncio
async def test_timeout_becomes_error_sample(monkeypatch):
    monkeypatch.setattr("eval.load_runner.httpx.AsyncClient", _RecordingClient)
    _RecordingClient.delay = 0.03
    spec = WorkloadSpec(
        name="F4_DETERMINISTIC",
        concurrency=1,
        samples=1,
        warmup_samples=0,
        timeout_seconds=0.005,
    )

    samples = await run_workload(
        "http://local", spec, lambda _sequence: RequestSpec(url="/slow")
    )

    assert samples[0].status_code is None
    assert samples[0].error == "TIMEOUT"
    assert samples[0].latency_ms >= 5


def _sample(sequence, latency, start, finish, *, status=200, error=None):
    return LatencySample(
        workload="F3_TICK",
        concurrency=5,
        sequence=sequence,
        status_code=status,
        latency_ms=latency,
        started_offset_ms=start,
        finished_offset_ms=finish,
        error=error,
    )


def test_summary_percentiles_throughput_and_saturation_are_exact():
    samples = [
        _sample(0, 10, 0, 10),
        _sample(1, 20, 0, 20),
        _sample(2, 30, 10, 40),
        _sample(3, 40, 20, 60, status=None, error="TIMEOUT"),
    ]

    summary = summarize_workload(samples, baseline_p95_ms=12)

    assert summary["p50_ms"] == 25
    assert summary["p95_ms"] == pytest.approx(38.5)
    assert summary["p99_ms"] == pytest.approx(39.7)
    assert summary["throughput_rps"] == pytest.approx(66.6666667)
    assert summary["error_count"] == 1
    assert summary["error_rate"] == 0.25
    assert summary["saturation_reasons"] == [
        "ERROR_RATE_GT_1_PERCENT",
        "P95_GT_2X_CCU1",
    ]


def test_first_saturation_level_includes_process_signals():
    summaries = [
        {"concurrency": 1, "saturation_reasons": [], "cpu_sustained_over_85": False},
        {"concurrency": 5, "saturation_reasons": [], "cpu_sustained_over_85": True},
        {"concurrency": 10, "saturation_reasons": ["P95_GT_2X_CCU1"]},
    ]

    assert first_saturation_level(summaries) == 5


def test_process_summary_flags_sustained_rss_growth():
    samples = [
        ProcessSample(offset_seconds=0, cpu_percent=20, rss_bytes=100_000_000),
        ProcessSample(offset_seconds=30, cpu_percent=90, rss_bytes=110_000_000),
        ProcessSample(offset_seconds=60, cpu_percent=30, rss_bytes=120_000_000),
    ]

    summary = summarize_process_samples(samples)

    assert summary["max_cpu_percent"] == 90
    assert summary["max_rss_bytes"] == 120_000_000
    assert summary["memory_slope_bytes_per_minute"] == pytest.approx(20_000_000)
    assert summary["memory_slope_unstable"] is True
    assert summary["cpu_sustained_over_85"] is False
