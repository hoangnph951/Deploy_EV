"""F1 US2 centralized policy and immutable assumption snapshots"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260808_1700"
down_revision = "20260808_1235"
branch_labels = None
depends_on = None


def _assumptions_type():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "policy_configs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("policy_version", sa.String(length=64), nullable=False, unique=True),
        sa.Column("reserve_soc_percent", sa.Float(), nullable=False, server_default="15.0"),
        sa.Column("stale_station_hours_threshold", sa.Float(), nullable=False, server_default="24.0"),
        sa.Column("route_deviation_km_threshold", sa.Float(), nullable=False, server_default="2.0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_policy_configs_active", "policy_configs", ["active"])
    op.bulk_insert(
        sa.table(
            "policy_configs",
            sa.column("id", sa.String),
            sa.column("policy_version", sa.String),
            sa.column("reserve_soc_percent", sa.Float),
            sa.column("stale_station_hours_threshold", sa.Float),
            sa.column("route_deviation_km_threshold", sa.Float),
            sa.column("active", sa.Boolean),
        ),
        [
            {
                "id": "pilot-policy-v1",
                "policy_version": "pilot-policy-v1",
                "reserve_soc_percent": 15.0,
                "stale_station_hours_threshold": 24.0,
                "route_deviation_km_threshold": 2.0,
                "active": True,
            }
        ],
    )

    vehicle_profiles = sa.table(
        "vehicle_profiles",
        sa.column("id", sa.String),
        sa.column("version", sa.String),
        sa.column("consumption_curve_json", sa.JSON),
    )
    op.execute(
        vehicle_profiles.update()
        .where(vehicle_profiles.c.id == "xe-x-mvp-v1")
        .values(
            version="xe_x_v1.0",
            consumption_curve_json={
                "baseline_wh_per_km": 175.0,
                "ambient_temperature_c": 25.0,
                "vehicle_payload_kg": 150.0,
                "terrain": "FLAT",
            },
        )
    )

    op.create_table(
        "plan_versions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "trip_id",
            sa.String(length=64),
            sa.ForeignKey("trips.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("assumptions", _assumptions_type(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("trip_id", "version", name="uq_plan_versions_trip_version"),
    )
    op.create_index("ix_plan_versions_trip_id", "plan_versions", ["trip_id"])
    op.create_index("ix_plan_versions_status", "plan_versions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_plan_versions_status", table_name="plan_versions")
    op.drop_index("ix_plan_versions_trip_id", table_name="plan_versions")
    op.drop_table("plan_versions")

    vehicle_profiles = sa.table(
        "vehicle_profiles",
        sa.column("id", sa.String),
        sa.column("version", sa.String),
        sa.column("consumption_curve_json", sa.JSON),
    )
    op.execute(
        vehicle_profiles.update()
        .where(vehicle_profiles.c.id == "xe-x-mvp-v1")
        .values(
            version="xe-x-mvp-v1",
            consumption_curve_json={
                "baseline_wh_per_km": 175.0,
                "temperature_c": 25.0,
                "payload_kg": 150.0,
            },
        )
    )

    op.drop_index("ix_policy_configs_active", table_name="policy_configs")
    op.drop_table("policy_configs")
