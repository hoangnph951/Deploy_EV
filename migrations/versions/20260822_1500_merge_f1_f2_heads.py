"""Merge the recovered F2 revision with the F1 production rollout branch.

Revision ID: 20260822_1500
Revises: 20260819_1200, 20260822_1200
"""

from __future__ import annotations

revision = "20260822_1500"
down_revision = ("20260819_1200", "20260822_1200")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Merge marker; both parent migrations own their schema changes."""


def downgrade() -> None:
    """Split back to the two parent heads without changing schema."""
