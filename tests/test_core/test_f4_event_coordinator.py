from datetime import UTC, datetime, timedelta

from src.packages.contracts.monitoring import MonitoringEvent
from src.packages.contracts.replanning import ActiveConstraintContext
from src.packages.core.replanning.application.event_coordinator import EventCoordinator

NOW = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)


def event(
    event_id: str,
    event_type: str,
    *,
    occurred_offset: int = 0,
    received_offset: int = 0,
    sequence: int | None = None,
    station_ids: list[str] | None = None,
) -> MonitoringEvent:
    return MonitoringEvent(
        event_id=event_id,
        trip_id="trip-1",
        event_type=event_type,
        occurred_at=NOW + timedelta(seconds=occurred_offset),
        received_at=NOW + timedelta(seconds=received_offset),
        telemetry_snapshot_id="telemetry-7",
        source_sequence=sequence,
        related_plan_version=3,
        severity="HIGH",
        threshold_ref="policy-v1",
        evidence_refs=[f"evidence:{event_id}"],
        correlation_id="correlation-1",
        station_ids=station_ids or [],
    )


def test_orders_by_occurrence_time_not_received_time() -> None:
    newer = event("event-b", "SOC_UNDERPERFORMANCE", occurred_offset=2, received_offset=1)
    older = event("event-a", "ROUTE_DEVIATION", occurred_offset=1, received_offset=3)

    result = EventCoordinator().coordinate([newer, older], context_version=4)

    assert [item.event_id for item in result.events] == ["event-a", "event-b"]


def test_duplicate_events_create_one_epoch_membership() -> None:
    duplicate = event("event-a", "ROUTE_DEVIATION")

    result = EventCoordinator().coordinate([duplicate, duplicate], context_version=4)

    assert result.duplicate_event_ids == ["event-a"]
    assert result.epoch.event_ids == ["event-a"]


def test_related_events_coalesce_and_merge_active_constraints() -> None:
    events = [
        event("event-route", "ROUTE_DEVIATION", sequence=1),
        event("event-soc", "SOC_UNDERPERFORMANCE", sequence=2),
        event(
            "event-station",
            "STATION_UNAVAILABLE",
            sequence=3,
            station_ids=["ST-10"],
        ),
    ]

    result = EventCoordinator().coordinate(
        events,
        context_version=9,
        active_constraints=ActiveConstraintContext(excluded_station_ids=["ST-OLD"]),
    )

    assert result.epoch.context_version == 9
    assert result.epoch.event_ids == ["event-route", "event-soc", "event-station"]
    assert result.active_constraints.route_deviation_active is True
    assert result.active_constraints.soc_underperformance_active is True
    assert result.active_constraints.excluded_station_ids == ["ST-OLD", "ST-10"]


def test_stale_telemetry_blocks_planning_in_constraint_envelope() -> None:
    result = EventCoordinator().coordinate(
        [event("event-stale", "STALE_TELEMETRY")], context_version=2
    )

    assert result.active_constraints.telemetry_blocked is True
    assert "FRESH_TELEMETRY_REQUIRED" in result.active_constraints.required_evidence


def test_nearby_snapshots_coalesce_to_latest_authoritative_snapshot() -> None:
    first = event("event-first", "ROUTE_DEVIATION", occurred_offset=0)
    second = event("event-second", "SOC_UNDERPERFORMANCE", occurred_offset=3)
    second.telemetry_snapshot_id = "telemetry-8"

    result = EventCoordinator(coalescing_window_seconds=5).coordinate(
        [second, first], context_version=5
    )

    assert result.epoch.event_ids == ["event-first", "event-second"]
    assert result.epoch.telemetry_snapshot_id == "telemetry-8"
