from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from src.packages.contracts.monitoring import MonitoringEvent
from src.packages.core.replanning.application.service import ReplanningOutcome
from src.packages.core.replanning.infrastructure.models import (
    AgentRunEventModel,
    AgentRunModel,
    DecisionEpochEventModel,
    DecisionEpochModel,
    MonitoringEventModel,
    PlanDiffModel,
    PlanningRunModel,
    PlanVersionEventModel,
    ToolRunModel,
    TripContextSnapshotModel,
)
from src.packages.core.trips.infrastructure.database import Base, build_session_factory


class SqlAlchemyReplanningAuditRepository:
    def __init__(self, database_url: str, *, ensure_schema: bool = False):
        self.engine, self.session_factory = build_session_factory(database_url)
        if ensure_schema:
            Base.metadata.create_all(self.engine)

    def save_run(self, outcome: ReplanningOutcome, events: list[MonitoringEvent]) -> None:
        now = datetime.now(UTC)
        with self.session_factory() as session:
            for event in events:
                if session.get(MonitoringEventModel, event.event_id) is None:
                    session.add(MonitoringEventModel(
                        id=event.event_id, trip_id=event.trip_id, event_type=event.event_type,
                        occurred_at=event.occurred_at, received_at=event.received_at,
                        source_sequence=event.source_sequence,
                        telemetry_snapshot_id=event.telemetry_snapshot_id,
                        related_plan_version=event.related_plan_version,
                        severity=event.severity, correlation_id=event.correlation_id,
                        causation_id=event.causation_id, status="ACTIVE",
                        evidence_json={"refs": event.evidence_refs, "station_ids": event.station_ids},
                    ))
            # Persist monitoring events before association rows reference them.
            session.flush()
            epoch = outcome.epoch
            session.add(DecisionEpochModel(
                id=epoch.epoch_id, trip_id=epoch.trip_id,
                telemetry_snapshot_id=epoch.telemetry_snapshot_id,
                context_version=epoch.context_version,
                base_plan_version=epoch.base_plan_version,
                opened_at=epoch.opened_at, sealed_at=epoch.sealed_at, status=epoch.status,
            ))
            # Persist FK parents before association rows. Without explicit ORM
            # relationships SQLAlchemy cannot infer the required flush order.
            session.flush()
            for event in events:
                session.add(DecisionEpochEventModel(epoch_id=epoch.epoch_id, event_id=event.event_id))
            context = outcome.context
            session.add(TripContextSnapshotModel(
                id=str(uuid4()), trip_id=context.trip_id,
                context_version=context.context_version,
                telemetry_snapshot_id=context.telemetry_snapshot_id,
                confirmed_plan_version=context.current_confirmed_plan_version,
                pending_plan_version=context.pending_plan_version,
                snapshot_json=context.model_dump(mode="json"), created_at=context.created_at,
            ))
            input_hash = hashlib.sha256(
                f"{context.trip_id}:{epoch.epoch_id}:{context.context_version}".encode()
            ).hexdigest()
            session.add(AgentRunModel(
                id=outcome.agent_run_id, trip_id=context.trip_id,
                decision_epoch_id=epoch.epoch_id, context_version=context.context_version,
                model="openai-or-deterministic-fallback", prompt_version="f4-supervisor-v3",
                policy_version=context.policy_version,
                assessment_json=outcome.assessment.model_dump(mode="json"),
                action_json={
                    "action": outcome.action.model_dump(mode="json"),
                    "reflection": outcome.reflection.model_dump(mode="json"),
                }, status=outcome.status,
                input_hash=input_hash, created_at=outcome.created_at, updated_at=now,
            ))
            # Flush AgentRun before inserting its association and child rows.
            session.flush()
            for event in events:
                session.add(AgentRunEventModel(agent_run_id=outcome.agent_run_id, event_id=event.event_id))
            for tool in outcome.tool_runs:
                session.add(ToolRunModel(
                    id=str(uuid4()), agent_run_id=outcome.agent_run_id,
                    sequence=tool.sequence, tool=tool.tool, input_hash=input_hash,
                    output_json={"reason_codes": tool.reason_codes}, provider=tool.provider,
                    provenance_json={"refs": tool.provenance_refs}, freshness=tool.freshness,
                    latency_ms=0, error=None,
                ))
            session.add(PlanningRunModel(
                id=outcome.agent_run_id, trip_id=context.trip_id,
                agent_run_id=outcome.agent_run_id,
                base_plan_version=epoch.base_plan_version,
                context_version=context.context_version, status=outcome.status, attempt=1,
                request_snapshot={
                    "trip_id": context.trip_id,
                    "context_version": context.context_version,
                    "telemetry_snapshot_id": context.telemetry_snapshot_id,
                    "event_ids": [event.event_id for event in events],
                    "event_types": [event.event_type for event in events],
                },
                idempotency_key=input_hash,
                outcome_json={"candidate": outcome.candidate},
                created_at=outcome.created_at, updated_at=now,
            ))
            if outcome.plan_diff_id and outcome.plan_diff:
                candidate_version = int((outcome.candidate or {}).get("plan_version") or 0)
                session.add(PlanDiffModel(
                    id=outcome.plan_diff_id, trip_id=context.trip_id,
                    base_version=epoch.base_plan_version,
                    candidate_version=candidate_version,
                    context_version=context.context_version,
                    telemetry_snapshot_id=context.telemetry_snapshot_id,
                    metrics_json=outcome.plan_diff,
                    provenance_json={"refs": [f"telemetry:{context.telemetry_snapshot_id}"]},
                ))
            candidate_outcome = (outcome.candidate or {}).get("outcome") or {}
            candidate_plan_id = (candidate_outcome.get("plan") or {}).get("plan_id")
            if candidate_plan_id:
                for event in events:
                    session.add(PlanVersionEventModel(
                        plan_version_id=candidate_plan_id,
                        event_id=event.event_id,
                        relationship_type="TRIGGERED_CANDIDATE",
                    ))
            session.commit()
