"""Reconcile databases stamped past F4 without its schema changes.

Revision ID: 20260827_0900
Revises: 20260826_2200
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260827_0900"
down_revision = "20260826_2200"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _column_names(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    plan_columns = _column_names("plan_versions")
    if "base_plan_version" not in plan_columns:
        op.add_column("plan_versions", sa.Column("base_plan_version", sa.Integer(), nullable=True))
    if "context_version" not in plan_columns:
        op.add_column("plan_versions", sa.Column("context_version", sa.Integer(), nullable=True))

    tables = _table_names()
    if "monitoring_events" not in tables:
        op.create_table(
            "monitoring_events",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("trip_id", sa.String(64), nullable=False),
            sa.Column("event_type", sa.String(32), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source_sequence", sa.Integer()),
            sa.Column("telemetry_snapshot_id", sa.String(64)),
            sa.Column("related_plan_version", sa.Integer(), nullable=False),
            sa.Column("severity", sa.String(16), nullable=False),
            sa.Column("correlation_id", sa.String(64), nullable=False),
            sa.Column("causation_id", sa.String(64)),
            sa.Column("status", sa.String(24), nullable=False),
            sa.Column("evidence_json", sa.JSON(), nullable=False),
            sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_monitoring_events_trip_id", "monitoring_events", ["trip_id"])

    tables = _table_names()
    if "decision_epochs" not in tables:
        op.create_table(
            "decision_epochs",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("trip_id", sa.String(64), nullable=False),
            sa.Column("telemetry_snapshot_id", sa.String(64), nullable=False),
            sa.Column("context_version", sa.Integer(), nullable=False),
            sa.Column("base_plan_version", sa.Integer(), nullable=False),
            sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("sealed_at", sa.DateTime(timezone=True)),
            sa.Column("status", sa.String(24), nullable=False),
            sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        )
    if "decision_epoch_events" not in tables:
        op.create_table(
            "decision_epoch_events",
            sa.Column("epoch_id", sa.String(64), primary_key=True),
            sa.Column("event_id", sa.String(64), primary_key=True),
            sa.ForeignKeyConstraint(["epoch_id"], ["decision_epochs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["event_id"], ["monitoring_events.id"], ondelete="CASCADE"),
        )
    if "trip_context_snapshots" not in tables:
        op.create_table(
            "trip_context_snapshots",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("trip_id", sa.String(64), nullable=False),
            sa.Column("context_version", sa.Integer(), nullable=False),
            sa.Column("telemetry_snapshot_id", sa.String(64), nullable=False),
            sa.Column("confirmed_plan_version", sa.Integer(), nullable=False),
            sa.Column("pending_plan_version", sa.Integer()),
            sa.Column("snapshot_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("trip_id", "context_version", name="uq_trip_context_version"),
        )
    if "agent_runs" not in tables:
        op.create_table(
            "agent_runs",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("trip_id", sa.String(64), nullable=False),
            sa.Column("decision_epoch_id", sa.String(64), nullable=False),
            sa.Column("context_version", sa.Integer(), nullable=False),
            sa.Column("model", sa.String(128), nullable=False),
            sa.Column("prompt_version", sa.String(64), nullable=False),
            sa.Column("policy_version", sa.String(64), nullable=False),
            sa.Column("assessment_json", sa.JSON(), nullable=False),
            sa.Column("action_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("input_hash", sa.String(128), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["decision_epoch_id"], ["decision_epochs.id"]),
        )
    if "agent_run_events" not in tables:
        op.create_table(
            "agent_run_events",
            sa.Column("agent_run_id", sa.String(64), primary_key=True),
            sa.Column("event_id", sa.String(64), primary_key=True),
            sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["event_id"], ["monitoring_events.id"], ondelete="CASCADE"),
        )
    if "tool_runs" not in tables:
        op.create_table(
            "tool_runs",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("agent_run_id", sa.String(64), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("tool", sa.String(64), nullable=False),
            sa.Column("input_hash", sa.String(128), nullable=False),
            sa.Column("output_json", sa.JSON(), nullable=False),
            sa.Column("provider", sa.String(64), nullable=False),
            sa.Column("provenance_json", sa.JSON(), nullable=False),
            sa.Column("freshness", sa.String(16), nullable=False),
            sa.Column("latency_ms", sa.Integer(), nullable=False),
            sa.Column("error", sa.Text()),
            sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        )

    planning_columns = _column_names("planning_runs")
    additions = (
        sa.Column("agent_run_id", sa.String(64), nullable=True),
        sa.Column("base_plan_version", sa.Integer(), nullable=True),
        sa.Column("context_version", sa.Integer(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("outcome_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in additions:
        if column.name not in planning_columns:
            op.add_column("planning_runs", column)
    if "idempotency_key" not in planning_columns:
        op.create_unique_constraint("uq_planning_runs_idempotency_key", "planning_runs", ["idempotency_key"])
    if "agent_run_id" not in planning_columns:
        op.create_foreign_key(
            "fk_planning_runs_agent_run_id", "planning_runs", "agent_runs", ["agent_run_id"], ["id"]
        )

    tables = _table_names()
    if "plan_diffs" not in tables:
        op.create_table(
            "plan_diffs",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("trip_id", sa.String(64), nullable=False),
            sa.Column("base_version", sa.Integer(), nullable=False),
            sa.Column("candidate_version", sa.Integer(), nullable=False),
            sa.Column("context_version", sa.Integer(), nullable=False),
            sa.Column("telemetry_snapshot_id", sa.String(64), nullable=False),
            sa.Column("metrics_json", sa.JSON(), nullable=False),
            sa.Column("provenance_json", sa.JSON(), nullable=False),
            sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        )
    if "plan_version_events" not in tables:
        op.create_table(
            "plan_version_events",
            sa.Column("plan_version_id", sa.String(64), primary_key=True),
            sa.Column("event_id", sa.String(64), primary_key=True),
            sa.Column("relationship_type", sa.String(32), nullable=False),
            sa.ForeignKeyConstraint(["plan_version_id"], ["plan_versions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["event_id"], ["monitoring_events.id"], ondelete="CASCADE"),
        )


def downgrade() -> None:
    # This migration repairs potentially pre-existing production data. A
    # destructive automatic downgrade would not be safe.
    raise RuntimeError("The F4 schema reconciliation migration cannot be downgraded safely.")
