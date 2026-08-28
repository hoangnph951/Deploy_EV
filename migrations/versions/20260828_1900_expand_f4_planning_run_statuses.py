"""Expand planning run statuses for F4 outcomes.

Revision ID: 20260828_1900
Revises: 20260828_1800
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260828_1900"
down_revision = "20260828_1800"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "ck_planning_runs_status"
LEGACY_STATUSES = ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED")
F4_STATUSES = ("INFEASIBLE", "INSUFFICIENT_EVIDENCE", "SEARCH_EXHAUSTED")


def _status_check(statuses: tuple[str, ...]) -> str:
    values = ", ".join(f"'{status}'" for status in statuses)
    return f"status IN ({values})"


def _replace_status_constraint(statuses: tuple[str, ...]) -> None:
    inspector = sa.inspect(op.get_bind())
    constraints = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("planning_runs")
    }
    with op.batch_alter_table("planning_runs") as batch:
        if CONSTRAINT_NAME in constraints:
            batch.drop_constraint(CONSTRAINT_NAME, type_="check")
        batch.create_check_constraint(CONSTRAINT_NAME, _status_check(statuses))


def upgrade() -> None:
    _replace_status_constraint(LEGACY_STATUSES + F4_STATUSES)


def downgrade() -> None:
    _replace_status_constraint(LEGACY_STATUSES)
