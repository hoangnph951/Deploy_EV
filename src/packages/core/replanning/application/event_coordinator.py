from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from src.packages.contracts.monitoring import MonitoringEvent
from src.packages.contracts.replanning import ActiveConstraintContext, DecisionEpoch


@dataclass(frozen=True)
class CoordinationResult:
    events: list[MonitoringEvent]
    epoch: DecisionEpoch
    active_constraints: ActiveConstraintContext
    duplicate_event_ids: list[str]


class EventCoordinator:
    """Deterministic event ordering, deduplication, coalescing and constraint merge."""

    def __init__(self, coalescing_window_seconds: float = 5.0):
        self.coalescing_window_seconds = coalescing_window_seconds

    def coordinate(
        self,
        events: list[MonitoringEvent],
        *,
        context_version: int,
        active_constraints: ActiveConstraintContext | None = None,
    ) -> CoordinationResult:
        if not events:
            raise ValueError("At least one monitoring event is required.")
        unique: dict[str, MonitoringEvent] = {}
        duplicates: list[str] = []
        for item in events:
            if item.event_id in unique:
                if item.event_id not in duplicates:
                    duplicates.append(item.event_id)
                continue
            unique[item.event_id] = item
        ordered = sorted(
            unique.values(),
            key=lambda item: (
                item.occurred_at,
                item.source_sequence if item.source_sequence is not None else 2**63 - 1,
                item.received_at,
                item.event_id,
            ),
        )
        trip_ids = {item.trip_id for item in ordered}
        snapshots = {item.telemetry_snapshot_id for item in ordered}
        within_window = (
            ordered[-1].occurred_at - ordered[0].occurred_at
        ).total_seconds() <= self.coalescing_window_seconds
        if len(trip_ids) != 1 or (len(snapshots) != 1 and not within_window):
            raise ValueError(
                "Events in one decision epoch must share trip and snapshot or coalescing window."
            )

        merged = (active_constraints or ActiveConstraintContext()).model_copy(deep=True)
        excluded = list(merged.excluded_station_ids)
        required = list(merged.required_evidence)
        reasons = list(merged.unresolved_reason_codes)
        for item in ordered:
            if item.event_type == "ROUTE_DEVIATION":
                merged.route_deviation_active = True
            elif item.event_type == "SOC_UNDERPERFORMANCE":
                merged.soc_underperformance_active = True
            elif item.event_type == "STALE_TELEMETRY":
                merged.telemetry_blocked = True
                if "FRESH_TELEMETRY_REQUIRED" not in required:
                    required.append("FRESH_TELEMETRY_REQUIRED")
            elif item.event_type == "STATION_UNAVAILABLE":
                for station_id in item.station_ids:
                    if station_id not in excluded:
                        excluded.append(station_id)
            code = f"ACTIVE_{item.event_type}"
            if code not in reasons:
                reasons.append(code)
        merged.excluded_station_ids = excluded
        merged.required_evidence = required
        merged.unresolved_reason_codes = reasons
        now = datetime.now(UTC)
        first = ordered[0]
        latest = ordered[-1]
        epoch = DecisionEpoch(
            epoch_id=str(uuid4()),
            trip_id=first.trip_id,
            telemetry_snapshot_id=latest.telemetry_snapshot_id or "unknown",
            context_version=context_version,
            base_plan_version=max(item.related_plan_version for item in ordered),
            event_ids=[item.event_id for item in ordered],
            opened_at=now,
            sealed_at=now,
            status="SEALED",
        )
        return CoordinationResult(ordered, epoch, merged, duplicates)
