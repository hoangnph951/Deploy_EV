from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from src.packages.contracts.monitoring import MonitoringEvent, TelemetrySnapshot
from src.packages.contracts.replanning import ActiveConstraintContext, TripContextSnapshot
from src.packages.core.replanning.application.event_coordinator import EventCoordinator


@dataclass(frozen=True)
class ContextAdvanceResult:
    snapshot: TripContextSnapshot
    stale_pending_plan_version: int | None


class TripContextManager:
    def advance(
        self,
        *,
        previous: TripContextSnapshot,
        events: list[MonitoringEvent],
        telemetry: TelemetrySnapshot,
        resolved_reason_codes: list[str] | None = None,
    ) -> ContextAdvanceResult:
        constraints = previous.unresolved_constraints.model_copy(deep=True)
        resolved = set(resolved_reason_codes or [])
        if "ACTIVE_ROUTE_DEVIATION" in resolved:
            constraints.route_deviation_active = False
            self._remove_reason(constraints, "ACTIVE_ROUTE_DEVIATION")
        if "ACTIVE_SOC_UNDERPERFORMANCE" in resolved:
            constraints.soc_underperformance_active = False
            self._remove_reason(constraints, "ACTIVE_SOC_UNDERPERFORMANCE")
        if "ACTIVE_STALE_TELEMETRY" in resolved:
            constraints.telemetry_blocked = False
            self._remove_reason(constraints, "ACTIVE_STALE_TELEMETRY")
            constraints.required_evidence = [
                code for code in constraints.required_evidence if code != "FRESH_TELEMETRY_REQUIRED"
            ]

        coordinated = EventCoordinator().coordinate(
            events,
            context_version=previous.context_version + 1,
            active_constraints=constraints,
        )
        snapshot_id = telemetry.snapshot_id or coordinated.epoch.telemetry_snapshot_id
        snapshot = TripContextSnapshot(
            trip_id=previous.trip_id,
            context_version=previous.context_version + 1,
            current_confirmed_plan_version=previous.current_confirmed_plan_version,
            pending_plan_version=None,
            telemetry_snapshot_id=snapshot_id,
            current_lat=telemetry.lat,
            current_lng=telemetry.lon,
            current_soc_percent=telemetry.soc_percent,
            destination_lat=previous.destination_lat,
            destination_lng=previous.destination_lng,
            vehicle_profile_version=previous.vehicle_profile_version,
            policy_version=previous.policy_version,
            assumption_snapshot_id=previous.assumption_snapshot_id,
            active_event_ids=list(dict.fromkeys(previous.active_event_ids + coordinated.epoch.event_ids)),
            unresolved_constraints=coordinated.active_constraints,
            created_at=datetime.now(UTC),
        )
        return ContextAdvanceResult(snapshot, previous.pending_plan_version)

    @staticmethod
    def _remove_reason(constraints: ActiveConstraintContext, reason: str) -> None:
        constraints.unresolved_reason_codes = [
            item for item in constraints.unresolved_reason_codes if item != reason
        ]
