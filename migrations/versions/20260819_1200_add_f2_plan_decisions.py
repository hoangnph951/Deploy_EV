"""Add Feature 2 plan confirmation and audit fields.

Revision ID: 20260819_1200
Revises: 20260815_0130
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260819_1200"
down_revision = "20260815_0130"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trips", sa.Column("confirmed_plan_version", sa.Integer(), nullable=True))
    op.add_column("plan_versions", sa.Column("decision_reason", sa.Text(), nullable=True))
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("trip_id", sa.String(length=64), nullable=False),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_audit_logs_trip_id", "audit_logs", ["trip_id"])
    op.create_index("ix_audit_logs_plan_id", "audit_logs", ["plan_id"])
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_actor_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_plan_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_trip_id", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_column("trips", "confirmed_plan_version")
    op.drop_column("plan_versions", "decision_reason")
