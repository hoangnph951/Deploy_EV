from datetime import UTC, datetime

from src.packages.contracts.monitoring import MonitoringEvent, TelemetrySnapshot
from src.packages.contracts.replanning import ActiveConstraintContext, TripContextSnapshot
from src.packages.core.replanning.application.context_manager import TripContextManager

NOW = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)


def telemetry(snapshot_id: str = "telemetry-8") -> TelemetrySnapshot:
    return TelemetrySnapshot(
        snapshot_id=snapshot_id,
        lat=21.0,
        lon=105.0,
        soc_percent=42.0,
        expected_soc_percent=50.0,
        speed_kph=50.0,
        distance_km=30.0,
        progress_percent=25.0,
        recorded_at=NOW,
    )


def station_event() -> MonitoringEvent:
    return MonitoringEvent(
        event_id="event-station",
        trip_id="trip-1",
        event_type="STATION_UNAVAILABLE",
        occurred_at=NOW,
        received_at=NOW,
        telemetry_snapshot_id="telemetry-8",
        related_plan_version=3,
        severity="HIGH",
        evidence_refs=["station-snapshot:ST-10"],
        correlation_id="corr-1",
        station_ids=["ST-10"],
    )


def previous_context() -> TripContextSnapshot:
    return TripContextSnapshot(
        trip_id="trip-1",
        context_version=7,
        current_confirmed_plan_version=3,
        pending_plan_version=4,
        telemetry_snapshot_id="telemetry-7",
        current_lat=21.1,
        current_lng=105.1,
        current_soc_percent=50.0,
        destination_lat=18.7,
        destination_lng=105.7,
        vehicle_profile_version="vf6-v1",
        policy_version="policy-v1",
        assumption_snapshot_id="assumption-1",
        active_event_ids=["event-route"],
        unresolved_constraints=ActiveConstraintContext(route_deviation_active=True),
        created_at=NOW,
    )


def test_new_event_advances_context_and_stales_old_pending_candidate() -> None:
    result = TripContextManager().advance(
        previous=previous_context(), events=[station_event()], telemetry=telemetry()
    )

    assert result.snapshot.context_version == 8
    assert result.snapshot.current_confirmed_plan_version == 3
    assert result.snapshot.pending_plan_version is None
    assert result.stale_pending_plan_version == 4
    assert result.snapshot.unresolved_constraints.route_deviation_active is True
    assert result.snapshot.unresolved_constraints.excluded_station_ids == ["ST-10"]


def test_resolved_constraints_are_not_carried_forward() -> None:
    result = TripContextManager().advance(
        previous=previous_context(),
        events=[station_event()],
        telemetry=telemetry(),
        resolved_reason_codes=["ACTIVE_ROUTE_DEVIATION"],
    )

    assert result.snapshot.unresolved_constraints.route_deviation_active is False
