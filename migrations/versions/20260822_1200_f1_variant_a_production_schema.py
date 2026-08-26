"""F1 Variant A station catalog, graph, planning runs, and normalized proposals."""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType

revision = "20260822_1200"
down_revision = "20260815_0130"
branch_labels = None
depends_on = None


class GeographyPoint(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **_kwargs) -> str:
        return "GEOGRAPHY(POINT, 4326)"


def _json_type():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _bigint_pk():
    return sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def _location_type():
    if op.get_bind().dialect.name == "postgresql":
        return GeographyPoint()
    return sa.String(length=128)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "charging_dataset_versions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("generation", sa.String(length=255), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_last_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", _json_type(), nullable=True),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'SUPERSEDED', 'FAILED')",
            name="ck_charging_dataset_versions_status",
        ),
    )
    op.create_index(
        "ix_charging_dataset_versions_provider",
        "charging_dataset_versions",
        ["provider"],
    )
    op.create_index(
        "ix_charging_dataset_versions_status",
        "charging_dataset_versions",
        ["status"],
    )
    op.create_index(
        "uq_charging_dataset_versions_active_provider",
        "charging_dataset_versions",
        ["provider"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
        sqlite_where=sa.text("status = 'ACTIVE'"),
    )

    op.create_table(
        "charging_locations",
        sa.Column("id", _bigint_pk(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column(
            "dataset_version_id",
            sa.String(length=64),
            sa.ForeignKey("charging_dataset_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("category_slug", sa.String(length=128), nullable=True),
        sa.Column("access_type", sa.String(length=64), nullable=True),
        sa.Column("charging_publish", sa.Boolean(), nullable=False),
        sa.Column("station_status", sa.String(length=32), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("location", _location_type(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_payload", _json_type(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("detail_quality", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "provider",
            "external_id",
            name="uq_charging_locations_provider_external",
        ),
        sa.CheckConstraint(
            "detail_quality IN ('VERIFIED', 'PARTIAL', 'UNVERIFIED')",
            name="ck_charging_locations_detail_quality",
        ),
    )
    op.create_index("ix_charging_locations_provider", "charging_locations", ["provider"])
    op.create_index("ix_charging_locations_active", "charging_locations", ["active"])
    op.create_index(
        "ix_charging_locations_station_status",
        "charging_locations",
        ["station_status"],
    )
    op.create_index(
        "ix_charging_locations_dataset_version_id",
        "charging_locations",
        ["dataset_version_id"],
    )
    if bind.dialect.name == "postgresql":
        op.create_index(
            "ix_charging_locations_location_gist",
            "charging_locations",
            ["location"],
            postgresql_using="gist",
        )

    op.create_table(
        "charging_evses",
        sa.Column("id", _bigint_pk(), primary_key=True, autoincrement=True),
        sa.Column(
            "location_id",
            _bigint_pk(),
            sa.ForeignKey("charging_locations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_evse_id", sa.String(length=255), nullable=True),
        sa.Column("depot_status", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_payload", _json_type(), nullable=True),
    )
    op.create_index("ix_charging_evses_location_id", "charging_evses", ["location_id"])

    op.create_table(
        "charging_connectors",
        sa.Column("id", _bigint_pk(), primary_key=True, autoincrement=True),
        sa.Column(
            "evse_id",
            _bigint_pk(),
            sa.ForeignKey("charging_evses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("connector_type", sa.String(length=128), nullable=False),
        sa.Column("normalized_connector", sa.String(length=64), nullable=False),
        sa.Column("max_electric_power_kw", sa.Float(), nullable=False),
        sa.Column("raw_payload", _json_type(), nullable=True),
    )
    op.create_index("ix_charging_connectors_evse_id", "charging_connectors", ["evse_id"])
    op.create_index(
        "ix_charging_connectors_normalized_connector",
        "charging_connectors",
        ["normalized_connector"],
    )

    op.create_table(
        "station_external_evidence",
        sa.Column("id", _bigint_pk(), primary_key=True, autoincrement=True),
        sa.Column(
            "location_id",
            _bigint_pk(),
            sa.ForeignKey("charging_locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("field_name", sa.String(length=128), nullable=False),
        sa.Column("field_value_json", _json_type(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column("raw_evidence", _json_type(), nullable=True),
        sa.CheckConstraint(
            "verification_status IN ('UNVERIFIED', 'CORROBORATED', 'REJECTED')",
            name="ck_station_external_evidence_status",
        ),
    )
    op.create_index(
        "ix_station_external_evidence_location_id",
        "station_external_evidence",
        ["location_id"],
    )
    op.create_index(
        "ix_station_external_evidence_provider",
        "station_external_evidence",
        ["provider"],
    )

    op.create_table(
        "station_edges",
        sa.Column("id", _bigint_pk(), primary_key=True, autoincrement=True),
        sa.Column(
            "from_location_id",
            _bigint_pk(),
            sa.ForeignKey("charging_locations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "to_location_id",
            _bigint_pk(),
            sa.ForeignKey("charging_locations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("routing_provider", sa.String(length=64), nullable=False),
        sa.Column("routing_profile", sa.String(length=64), nullable=False),
        sa.Column("road_version", sa.String(length=128), nullable=False),
        sa.Column("distance_km", sa.Float(), nullable=False),
        sa.Column("duration_minutes", sa.Float(), nullable=False),
        sa.Column("geometry_polyline", sa.Text(), nullable=True),
        sa.Column("provider_source_url", sa.Text(), nullable=True),
        sa.Column("provider_retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "from_location_id",
            "to_location_id",
            "routing_provider",
            "road_version",
            name="uq_station_edges_directed_version",
        ),
    )
    op.create_index("ix_station_edges_from_location_id", "station_edges", ["from_location_id"])
    op.create_index("ix_station_edges_to_location_id", "station_edges", ["to_location_id"])

    op.create_table(
        "planning_runs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "trip_id",
            sa.String(length=64),
            sa.ForeignKey("trips.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column("request_snapshot", _json_type(), nullable=False),
        sa.Column("result_code", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_detail", _json_type(), nullable=True),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED')",
            name="ck_planning_runs_status",
        ),
    )
    op.create_index("ix_planning_runs_trip_id", "planning_runs", ["trip_id"])
    op.create_index("ix_planning_runs_status", "planning_runs", ["status"])

    with op.batch_alter_table("plan_versions") as batch:
        batch.add_column(sa.Column("planning_run_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("rank", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(
            sa.Column("strategy", sa.String(length=32), nullable=False, server_default="BALANCED")
        )
        batch.add_column(
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch.add_column(sa.Column("proposal", _json_type(), nullable=True))
        batch.create_foreign_key(
            "fk_plan_versions_planning_run_id",
            "planning_runs",
            ["planning_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.drop_constraint("uq_plan_versions_trip_version", type_="unique")
        batch.create_unique_constraint(
            "uq_plan_versions_trip_version_rank",
            ["trip_id", "version", "rank"],
        )
    op.create_index("ix_plan_versions_planning_run_id", "plan_versions", ["planning_run_id"])

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
    bind = op.get_bind()
    plan_versions = sa.table(
        "plan_versions",
        sa.column("id", sa.String),
        sa.column("assumptions", _json_type()),
        sa.column("proposal", _json_type()),
        sa.column("is_primary", sa.Boolean),
    )
    rows = bind.execute(
        sa.select(plan_versions.c.id, plan_versions.c.assumptions, plan_versions.c.proposal).where(
            plan_versions.c.is_primary.is_(True)
        )
    ).all()
    for row in rows:
        assumptions = row.assumptions
        if isinstance(assumptions, str):
            assumptions = json.loads(assumptions)
        assumptions = dict(assumptions or {})
        if row.proposal is not None:
            assumptions["proposal"] = row.proposal
        bind.execute(
            plan_versions.update()
            .where(plan_versions.c.id == row.id)
            .values(assumptions=assumptions)
        )
    bind.execute(sa.text("DELETE FROM plan_versions WHERE is_primary = false"))

    op.drop_index("ix_plan_versions_planning_run_id", table_name="plan_versions")
    with op.batch_alter_table("plan_versions") as batch:
        batch.drop_constraint("uq_plan_versions_trip_version_rank", type_="unique")
        batch.create_unique_constraint(
            "uq_plan_versions_trip_version",
            ["trip_id", "version"],
        )
        batch.drop_constraint("fk_plan_versions_planning_run_id", type_="foreignkey")
        batch.drop_column("proposal")
        batch.drop_column("is_primary")
        batch.drop_column("strategy")
        batch.drop_column("rank")
        batch.drop_column("planning_run_id")

    op.drop_index("ix_planning_runs_status", table_name="planning_runs")
    op.drop_index("ix_planning_runs_trip_id", table_name="planning_runs")
    op.drop_table("planning_runs")
    op.drop_index("ix_station_edges_to_location_id", table_name="station_edges")
    op.drop_index("ix_station_edges_from_location_id", table_name="station_edges")
    op.drop_table("station_edges")
    op.drop_index("ix_station_external_evidence_provider", table_name="station_external_evidence")
    op.drop_index("ix_station_external_evidence_location_id", table_name="station_external_evidence")
    op.drop_table("station_external_evidence")
    op.drop_index("ix_charging_connectors_normalized_connector", table_name="charging_connectors")
    op.drop_index("ix_charging_connectors_evse_id", table_name="charging_connectors")
    op.drop_table("charging_connectors")
    op.drop_index("ix_charging_evses_location_id", table_name="charging_evses")
    op.drop_table("charging_evses")
    if bind.dialect.name == "postgresql":
        op.drop_index("ix_charging_locations_location_gist", table_name="charging_locations")
    op.drop_index("ix_charging_locations_dataset_version_id", table_name="charging_locations")
    op.drop_index("ix_charging_locations_station_status", table_name="charging_locations")
    op.drop_index("ix_charging_locations_active", table_name="charging_locations")
    op.drop_index("ix_charging_locations_provider", table_name="charging_locations")
    op.drop_table("charging_locations")
    op.drop_index(
        "uq_charging_dataset_versions_active_provider",
        table_name="charging_dataset_versions",
    )
    op.drop_index("ix_charging_dataset_versions_status", table_name="charging_dataset_versions")
    op.drop_index("ix_charging_dataset_versions_provider", table_name="charging_dataset_versions")
    op.drop_table("charging_dataset_versions")
