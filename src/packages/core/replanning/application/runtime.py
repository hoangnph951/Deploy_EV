from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from src.packages.contracts.monitoring import MonitoringEvent
from src.packages.contracts.replanning import (
    ActiveConstraintContext,
    TripContextSnapshot,
)
from src.packages.core.replanning.application.service import ReplanningOutcome
from src.packages.core.trips.application.errors import ForbiddenError, NotFoundError


@dataclass
class StoredRun:
    owner_id: str
    outcome: ReplanningOutcome


class ReplanningRuntimeStore:
    """Runtime cache; durable audit uses the F4 SQLAlchemy repository in production."""

    def __init__(self, audit_repository=None):
        self.audit_repository = audit_repository
        self.contexts: dict[str, TripContextSnapshot] = {}
        self.runs: dict[str, StoredRun] = {}
        self.owners: dict[str, str] = {}
        self.events: dict[str, list[MonitoringEvent]] = {}
        self.idempotent_runs: dict[str, str] = {}

    def initial_context(self, trip, plan_count: int) -> TripContextSnapshot:
        existing = self.contexts.get(trip.trip_id)
        if existing is not None:
            return existing
        context = TripContextSnapshot(
            trip_id=trip.trip_id,
            context_version=1,
            current_confirmed_plan_version=plan_count,
            pending_plan_version=plan_count or None,
            telemetry_snapshot_id="INITIAL",
            current_lat=trip.origin.lat,
            current_lng=trip.origin.lng,
            current_soc_percent=trip.initial_soc.value_percent,
            destination_lat=trip.destination.lat,
            destination_lng=trip.destination.lng,
            vehicle_profile_version=trip.assumptions.vehicle_profile_version,
            policy_version=trip.assumptions.policy_version,
            assumption_snapshot_id=f"trip:{trip.trip_id}:assumptions",
            active_event_ids=[],
            unresolved_constraints=ActiveConstraintContext(),
            created_at=datetime.now(UTC),
        )
        self.contexts[trip.trip_id] = context
        return context

    def save(
        self, owner_id: str, outcome: ReplanningOutcome,
        events: list[MonitoringEvent] | None = None,
    ) -> None:
        if self.audit_repository is not None:
            self.audit_repository.save_run(outcome, events or [])
        self.contexts[outcome.context.trip_id] = outcome.context
        self.owners[outcome.context.trip_id] = owner_id
        if events:
            known = {item.event_id for item in self.events.get(outcome.context.trip_id, [])}
            self.events.setdefault(outcome.context.trip_id, []).extend(
                item for item in events if item.event_id not in known
            )
        self.runs[outcome.agent_run_id] = StoredRun(owner_id, outcome)

    def find_idempotent(self, key: str, owner_id: str) -> ReplanningOutcome | None:
        run_id = self.idempotent_runs.get(key)
        return self.get_run(run_id, owner_id) if run_id else None

    def bind_idempotency(self, key: str, run_id: str) -> None:
        self.idempotent_runs[key] = run_id

    def get_run(self, run_id: str, owner_id: str) -> ReplanningOutcome:
        stored = self.runs.get(run_id)
        if stored is None:
            raise NotFoundError("AgentRun")
        if stored.owner_id != owner_id:
            raise ForbiddenError()
        return stored.outcome

    def authorize_trip(self, trip_id: str, owner_id: str) -> None:
        if trip_id not in self.contexts:
            raise NotFoundError("TripContext")
        if self.owners.get(trip_id) != owner_id:
            raise ForbiddenError()

    def get_context(self, trip_id: str, owner_id: str) -> TripContextSnapshot:
        self.authorize_trip(trip_id, owner_id)
        return self.contexts[trip_id]

    def get_events(self, trip_id: str, owner_id: str) -> list[MonitoringEvent]:
        self.authorize_trip(trip_id, owner_id)
        return self.events.get(trip_id, [])

    def get_epoch(self, trip_id: str, epoch_id: str, owner_id: str):
        self.authorize_trip(trip_id, owner_id)
        for stored in self.runs.values():
            if stored.outcome.context.trip_id == trip_id and stored.outcome.epoch.epoch_id == epoch_id:
                return stored.outcome.epoch
        raise NotFoundError("DecisionEpoch")
