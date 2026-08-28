"""Align F4 planning runs with the legacy request snapshot contract.

Revision ID: 20260828_1800
Revises: 20260827_0900
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260828_1800"
down_revision = "20260827_0900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("planning_runs")}
    if "request_snapshot" not in columns:
        op.add_column(
            "planning_runs",
            sa.Column(
                "request_snapshot", sa.JSON(), nullable=False,
                server_default=sa.text("'{}'"),
            ),
        )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("planning_runs")}
    if "request_snapshot" in columns:
        op.drop_column("planning_runs", "request_snapshot")
