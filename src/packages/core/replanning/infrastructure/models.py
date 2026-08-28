from __future__ import annotations

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.packages.core.trips.infrastructure import models as _trip_models  # noqa: F401
from src.packages.core.trips.infrastructure.database import Base


class MonitoringEventModel(Base):
    __tablename__ = "monitoring_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    occurred_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    source_sequence: Mapped[int | None] = mapped_column(Integer)
    telemetry_snapshot_id: Mapped[str | None] = mapped_column(String(64))
    related_plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    causation_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    evidence_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class DecisionEpochModel(Base):
    __tablename__ = "decision_epochs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    telemetry_snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    context_version: Mapped[int] = mapped_column(Integer, nullable=False)
    base_plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    opened_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    sealed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), nullable=False)


class DecisionEpochEventModel(Base):
    __tablename__ = "decision_epoch_events"
    epoch_id: Mapped[str] = mapped_column(ForeignKey("decision_epochs.id", ondelete="CASCADE"), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("monitoring_events.id", ondelete="CASCADE"), primary_key=True)


class TripContextSnapshotModel(Base):
    __tablename__ = "trip_context_snapshots"
    __table_args__ = (UniqueConstraint("trip_id", "context_version", name="uq_trip_context_version"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    context_version: Mapped[int] = mapped_column(Integer, nullable=False)
    telemetry_snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmed_plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    pending_plan_version: Mapped[int | None] = mapped_column(Integer)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentRunModel(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    decision_epoch_id: Mapped[str] = mapped_column(ForeignKey("decision_epochs.id"), index=True)
    context_version: Mapped[int] = mapped_column(Integer, nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    assessment_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    action_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentRunEventModel(Base):
    __tablename__ = "agent_run_events"
    agent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("monitoring_events.id", ondelete="CASCADE"), primary_key=True)


class ToolRunModel(Base):
    __tablename__ = "tool_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    tool: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    output_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provenance_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    freshness: Mapped[str] = mapped_column(String(16), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class PlanningRunModel(Base):
    __tablename__ = "planning_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'INFEASIBLE', "
            "'INSUFFICIENT_EVIDENCE', 'SEARCH_EXHAUSTED', 'FAILED')",
            name="ck_planning_runs_status",
        ),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    agent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    base_plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    context_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    # Kept for compatibility with the original F1 planning_runs schema.
    request_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    outcome_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class PlanDiffModel(Base):
    __tablename__ = "plan_diffs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    base_version: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    context_version: Mapped[int] = mapped_column(Integer, nullable=False)
    telemetry_snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    metrics_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    provenance_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class PlanVersionEventModel(Base):
    __tablename__ = "plan_version_events"
    plan_version_id: Mapped[str] = mapped_column(ForeignKey("plan_versions.id", ondelete="CASCADE"), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("monitoring_events.id", ondelete="CASCADE"), primary_key=True)
    relationship_type: Mapped[str] = mapped_column(String(32), nullable=False)
