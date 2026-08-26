"""Add atomic, resumable station graph versions."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260822_1700"
down_revision = "20260822_1500"
branch_labels = None
depends_on = None


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _bigint():
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "station_graph_versions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("routing_provider", sa.String(length=64), nullable=False),
        sa.Column("routing_profile", sa.String(length=64), nullable=False),
        sa.Column("road_version", sa.String(length=128), nullable=False),
        sa.Column(
            "station_dataset_version_id",
            sa.String(length=64),
            sa.ForeignKey("charging_dataset_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expected_node_count", sa.Integer(), nullable=False),
        sa.Column("processed_node_count", sa.Integer(), nullable=False),
        sa.Column("edge_count", _bigint(), nullable=False),
        sa.Column("last_location_id", _bigint(), nullable=True),
        sa.Column("metadata_json", _json_type(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('BUILDING', 'ACTIVE', 'SUPERSEDED', 'FAILED')",
            name="ck_station_graph_versions_status",
        ),
    )
    op.create_index(
        "ix_station_graph_versions_routing_provider",
        "station_graph_versions",
        ["routing_provider"],
    )
    op.create_index(
        "ix_station_graph_versions_road_version",
        "station_graph_versions",
        ["road_version"],
    )
    op.create_index(
        "ix_station_graph_versions_station_dataset_version_id",
        "station_graph_versions",
        ["station_dataset_version_id"],
    )
    op.create_index(
        "ix_station_graph_versions_status",
        "station_graph_versions",
        ["status"],
    )
    op.create_index(
        "uq_station_graph_versions_active_provider_profile",
        "station_graph_versions",
        ["routing_provider", "routing_profile"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
        sqlite_where=sa.text("status = 'ACTIVE'"),
    )

    with op.batch_alter_table("station_edges") as batch:
        batch.add_column(sa.Column("graph_version_id", sa.String(length=64), nullable=True))
        batch.create_foreign_key(
            "fk_station_edges_graph_version_id",
            "station_graph_versions",
            ["graph_version_id"],
            ["id"],
            ondelete="CASCADE",
        )

    _backfill_existing_edges()

    with op.batch_alter_table("station_edges") as batch:
        batch.alter_column("graph_version_id", existing_type=sa.String(length=64), nullable=False)
        batch.drop_constraint("uq_station_edges_directed_version", type_="unique")
        batch.create_unique_constraint(
            "uq_station_edges_graph_directed",
            ["graph_version_id", "from_location_id", "to_location_id"],
        )
        batch.create_index("ix_station_edges_graph_version_id", ["graph_version_id"])


def _backfill_existing_edges() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT
                e.routing_provider,
                e.routing_profile,
                e.road_version,
                MIN(l.dataset_version_id) AS dataset_version_id,
                COUNT(*) AS edge_count
            FROM station_edges e
            JOIN charging_locations l ON l.id = e.from_location_id
            GROUP BY e.routing_provider, e.routing_profile, e.road_version
            """
        )
    ).mappings()
    now = datetime.now(UTC)
    for row in rows:
        graph_version_id = str(uuid4())
        bind.execute(
            sa.text(
                """
                INSERT INTO station_graph_versions (
                    id, routing_provider, routing_profile, road_version,
                    station_dataset_version_id, status, started_at, completed_at,
                    expected_node_count, processed_node_count, edge_count,
                    last_location_id, metadata_json, failure_reason
                ) VALUES (
                    :id, :provider, :profile, :road_version,
                    :dataset_version_id, 'FAILED', :now, :now,
                    0, 0, :edge_count, NULL, NULL, :failure_reason
                )
                """
            ),
            {
                "id": graph_version_id,
                "provider": row["routing_provider"],
                "profile": row["routing_profile"],
                "road_version": row["road_version"],
                "dataset_version_id": row["dataset_version_id"],
                "now": now,
                "edge_count": row["edge_count"],
                "failure_reason": "Legacy edges predate atomic graph activation.",
            },
        )
        bind.execute(
            sa.text(
                """
                UPDATE station_edges
                SET graph_version_id = :graph_version_id
                WHERE routing_provider = :provider
                  AND routing_profile = :profile
                  AND road_version = :road_version
                """
            ),
            {
                "graph_version_id": graph_version_id,
                "provider": row["routing_provider"],
                "profile": row["routing_profile"],
                "road_version": row["road_version"],
            },
        )


def downgrade() -> None:
    with op.batch_alter_table("station_edges") as batch:
        batch.drop_index("ix_station_edges_graph_version_id")
        batch.drop_constraint("uq_station_edges_graph_directed", type_="unique")
        batch.create_unique_constraint(
            "uq_station_edges_directed_version",
            [
                "from_location_id",
                "to_location_id",
                "routing_provider",
                "road_version",
            ],
        )
        batch.drop_constraint("fk_station_edges_graph_version_id", type_="foreignkey")
        batch.drop_column("graph_version_id")

    op.drop_index(
        "uq_station_graph_versions_active_provider_profile",
        table_name="station_graph_versions",
    )
    op.drop_index("ix_station_graph_versions_status", table_name="station_graph_versions")
    op.drop_index(
        "ix_station_graph_versions_station_dataset_version_id",
        table_name="station_graph_versions",
    )
    op.drop_index("ix_station_graph_versions_road_version", table_name="station_graph_versions")
    op.drop_index(
        "ix_station_graph_versions_routing_provider",
        table_name="station_graph_versions",
    )
    op.drop_table("station_graph_versions")
