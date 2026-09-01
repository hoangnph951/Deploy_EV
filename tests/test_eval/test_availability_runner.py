from datetime import UTC, datetime

import pytest

from eval.availability_runner import (
    AvailabilitySample,
    calculate_error_windows,
    run_availability_soak,
    summarize_availability,
)


def _sample(offset, available, *, outcome=None, error=None):
    return AvailabilitySample(
        offset_seconds=offset,
        observed_at=datetime(2026, 9, 1, tzinfo=UTC),
        phase="TEST",
        available=available,
        status_code=200 if available else None,
        outcome=outcome,
        latency_ms=1,
        error=error,
    )


def test_contiguous_failures_merge_and_recovery_closes_window():
    samples = [
        _sample(0, True),
        _sample(1, False, error="CONNECTION_ERROR"),
        _sample(2, False, error="CONNECTION_ERROR"),
        _sample(4, True),
        _sample(7, False, error="TIMEOUT"),
        _sample(9, True),
    ]

    windows = calculate_error_windows(samples)

    assert len(windows) == 2
    assert windows[0].started_offset_seconds == 1
    assert windows[0].recovered_offset_seconds == 4
    assert windows[0].downtime_seconds == 3
    assert windows[0].failure_count == 2
    assert windows[1].downtime_seconds == 2


def test_summary_calculates_downtime_longest_and_mttr():
    samples = [
        _sample(0, True),
        _sample(1, False),
        _sample(3, True),
        _sample(4, False),
        _sample(8, True),
    ]

    summary = summarize_availability(samples, duration_seconds=10)

    assert summary.availability_percent == 60
    assert summary.total_downtime_seconds == 6
    assert summary.longest_downtime_seconds == 4
    assert summary.mttr_seconds == 3
    assert "single-instance" in summary.limitation


@pytest.mark.parametrize(
    ("status", "outcome", "expected"),
    [
        (200, "INSUFFICIENT_EVIDENCE", True),
        (202, "SAFE_FALLBACK", True),
        (None, "CONNECTION_ERROR", False),
        (504, "TIMEOUT", False),
    ],
)
def test_typed_degradation_is_functionally_available(status, outcome, expected):
    from eval.availability_runner import _functional_availability

    assert _functional_availability(status, outcome) is expected


def test_open_error_window_uses_soak_end_for_downtime():
    samples = [_sample(8, False, error="CONNECTION_ERROR")]

    windows = calculate_error_windows(samples, end_offset_seconds=10)

    assert windows[0].recovered_offset_seconds is None
    assert windows[0].downtime_seconds == 2


class _FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        self.value += 0.01
        return self.value

    async def sleep(self, seconds):
        self.value += seconds


class _FakeProcess:
    def __init__(self):
        self.running = False
        self.fault = "NONE"
        self.faults = []
        self.stop_count = 0

    async def start(self):
        self.running = True

    async def wait_ready(self, timeout_seconds):
        assert timeout_seconds == 30
        return 0.1

    async def stop(self):
        self.running = False
        self.stop_count += 1

    async def set_fault(self, fault):
        self.fault = fault
        self.faults.append(fault)

    async def probe(self):
        if not self.running:
            return None, "CONNECTION_ERROR", "ConnectError"
        if self.fault == "LLM_TIMEOUT":
            return 200, "SAFE_FALLBACK", None
        if self.fault == "F1_PROVIDER_FAILURE":
            return 200, "INSUFFICIENT_EVIDENCE", None
        return 200, "OK", None


@pytest.mark.asyncio
async def test_soak_fault_schedule_records_degradation_restart_and_recovery():
    clock = _FakeClock()
    process = _FakeProcess()

    samples, summary = await run_availability_soak(
        process,
        duration_seconds=8,
        request_interval_seconds=1,
        _clock=clock,
        _sleep=clock.sleep,
    )

    assert "LLM_TIMEOUT" in process.faults
    assert "F1_PROVIDER_FAILURE" in process.faults
    assert process.faults.count("NONE") >= 2
    assert any(
        sample.phase == "LLM_TIMEOUT" and sample.available for sample in samples
    )
    assert any(
        sample.phase == "F1_PROVIDER_FAILURE" and sample.available
        for sample in samples
    )
    restart_index = next(
        index for index, sample in enumerate(samples)
        if sample.phase == "FORCED_RESTART"
    )
    assert samples[restart_index].available is False
    assert any(sample.available for sample in samples[restart_index + 1 :])
    assert summary.unavailable_count >= 1
    assert summary.total_downtime_seconds > 0
    assert process.running is False
