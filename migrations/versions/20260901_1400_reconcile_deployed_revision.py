"""Reconcile the revision already stamped in the deployed database.

Revision ID: 20260901_1400
Revises: 20260901_0000

The production database was stamped with ``20260901_1400`` by an earlier
deployment, but that revision file was not present in the repository history.
The running schema is already compatible with the current metadata, so this
bridge restores a resolvable Alembic graph without rewriting production data.
"""

from __future__ import annotations

revision = "20260901_1400"
down_revision = "20260901_0000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
