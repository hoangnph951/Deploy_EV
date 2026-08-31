"""Restore F2 ranked plan persistence on the F4 migration branch.

Revision ID: 20260831_1400
Revises: 20260828_1900
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260831_1400"
down_revision = "20260828_1900"
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("plan_versions")}

    with op.batch_alter_table("plan_versions") as batch:
        if "planning_run_id" not in columns:
            batch.add_column(sa.Column("planning_run_id", sa.String(length=64), nullable=True))
        if "rank" not in columns:
            batch.add_column(sa.Column("rank", sa.Integer(), nullable=False, server_default="1"))
        if "strategy" not in columns:
            batch.add_column(
                sa.Column("strategy", sa.String(length=32), nullable=False, server_default="BALANCED")
            )
        if "is_primary" not in columns:
            batch.add_column(
                sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.true())
            )
        if "proposal" not in columns:
            batch.add_column(sa.Column("proposal", _json_type(), nullable=True))

    inspector = sa.inspect(bind)
    foreign_keys = {foreign_key["name"] for foreign_key in inspector.get_foreign_keys("plan_versions")}
    unique_constraints = {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("plan_versions")
    }
    indexes = {index["name"] for index in inspector.get_indexes("plan_versions")}

    with op.batch_alter_table("plan_versions") as batch:
        if "fk_plan_versions_planning_run_id" not in foreign_keys:
            batch.create_foreign_key(
                "fk_plan_versions_planning_run_id",
                "planning_runs",
                ["planning_run_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if "uq_plan_versions_trip_version_rank" not in unique_constraints:
            for name, column_names in unique_constraints.items():
                if column_names == ("trip_id", "version"):
                    batch.drop_constraint(name, type_="unique")
            batch.create_unique_constraint(
                "uq_plan_versions_trip_version_rank",
                ["trip_id", "version", "rank"],
            )

    if "ix_plan_versions_planning_run_id" not in indexes:
        op.create_index(
            "ix_plan_versions_planning_run_id",
            "plan_versions",
            ["planning_run_id"],
        )

    plan_versions = sa.table(
        "plan_versions",
        sa.column("id", sa.String),
        sa.column("assumptions", _json_type()),
        sa.column("proposal", _json_type()),
    )
    rows = bind.execute(sa.select(plan_versions.c.id, plan_versions.c.assumptions)).all()
    for row in rows:
        assumptions = row.assumptions
        if isinstance(assumptions, str):
            assumptions = json.loads(assumptions)
        if not isinstance(assumptions, dict):
            continue
        proposal = assumptions.pop("proposal", None)
        if proposal is None:
            continue
        bind.execute(
            plan_versions.update()
            .where(plan_versions.c.id == row.id)
            .values(assumptions=assumptions, proposal=proposal)
        )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrading ranked F2 plans would discard alternatives and is not supported."
    )
