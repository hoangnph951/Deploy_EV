"""Remove the deprecated station graph persistence tables."""

from __future__ import annotations

from alembic import op


revision = "20260826_2200"
down_revision = "20260826_1200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The tables may already have been removed manually in Supabase.
    # CASCADE also removes any remaining indexes/foreign-key dependencies.
    op.execute("DROP TABLE IF EXISTS station_edges CASCADE")
    op.execute("DROP TABLE IF EXISTS station_graph_versions CASCADE")


def downgrade() -> None:
    raise RuntimeError(
        "Station graph persistence was intentionally removed; restore from backup "
        "or create a dedicated schema migration if graph support is needed again."
    )
