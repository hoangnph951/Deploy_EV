from datetime import UTC, datetime

import pytest

from src.packages.contracts.monitoring import TelemetrySnapshot
from src.packages.core.monitoring.application.monitoring_service import MonitoringService


def telemetry(*, route_km: float = 0, expected_soc: float = 50, actual_soc: float = 50, age: float = 0):
    return TelemetrySnapshot(
        event_id="telemetry-1",
        trip_id="trip-1",
        lat=21.0,
        lng=105.8,
        actual_soc_percent=actual_soc,
        expected_soc_percent=expected_soc,
        progress_percent=50,
        distance_to_route_km=route_km,
        scenario_id="scenario-1",
        simulation_run_id="run-1",
        tick=10,
        recorded_at=datetime.now(UTC),
        age_seconds=age,
    )


@pytest.mark.parametrize("distance", [1.99, 2.0])
def test_route_deviation_does_not_fire_at_or_below_boundary(distance):
    events = MonitoringService().evaluate(telemetry(route_km=distance), profile="NORMAL")
    assert events == []


def test_route_deviation_fires_strictly_above_two_km():
    events = MonitoringService().evaluate(telemetry(route_km=2.01), profile="NORMAL")
    assert [event.event_type for event in events] == ["ROUTE_DEVIATION"]


@pytest.mark.parametrize("gap", [4.9, 5.0])
def test_soc_underperformance_does_not_fire_at_or_below_boundary(gap):
    events = MonitoringService().evaluate(
        telemetry(expected_soc=50, actual_soc=50 - gap),
        profile="NORMAL",
    )
    assert events == []


def test_soc_underperformance_fires_strictly_above_five_percent():
    events = MonitoringService().evaluate(
        telemetry(expected_soc=50, actual_soc=44.9),
        profile="NORMAL",
    )
    assert [event.event_type for event in events] == ["SOC_UNDERPERFORMANCE"]


def test_stale_telemetry_requires_more_than_sixty_seconds_and_short_circuits_planning_events():
    service = MonitoringService()
    assert service.evaluate(telemetry(age=60), profile="NORMAL") == []

    events = service.evaluate(
        telemetry(age=61, route_km=3, expected_soc=50, actual_soc=40),
        profile="NORMAL",
    )
    assert [event.event_type for event in events] == ["STALE_TELEMETRY"]


def test_monitoring_event_is_deduplicated_by_type():
    events = MonitoringService().evaluate(
        telemetry(route_km=2.01),
        profile="NORMAL",
        already_emitted={"ROUTE_DEVIATION"},
    )
    assert events == []
