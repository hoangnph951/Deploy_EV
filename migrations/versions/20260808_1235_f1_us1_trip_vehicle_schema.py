"""F1 US1 trip and vehicle profile schema"""

import sqlalchemy as sa
from alembic import op

revision = "20260808_1235"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vehicle_profiles",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("battery_capacity_kwh", sa.Float(), nullable=False),
        sa.Column("usable_capacity_kwh", sa.Float(), nullable=False),
        sa.Column("max_charging_power_kw", sa.Float(), nullable=False),
        sa.Column("connector_type", sa.String(length=32), nullable=False),
        sa.Column("consumption_curve_json", sa.JSON(), nullable=False),
    )
    op.create_table(
        "trips",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("origin_address", sa.Text(), nullable=False),
        sa.Column("origin_lat", sa.Float(), nullable=False),
        sa.Column("origin_lng", sa.Float(), nullable=False),
        sa.Column("origin_source_type", sa.String(length=32), nullable=False),
        sa.Column("destination_address", sa.Text(), nullable=False),
        sa.Column("destination_lat", sa.Float(), nullable=False),
        sa.Column("destination_lng", sa.Float(), nullable=False),
        sa.Column("destination_source_type", sa.String(length=32), nullable=False),
        sa.Column("initial_soc_percent", sa.Float(), nullable=False),
        sa.Column("soc_source_type", sa.String(length=32), nullable=False),
        sa.Column("vehicle_profile_id", sa.String(length=64), nullable=False),
        sa.Column("preference", sa.String(length=32), nullable=False),
        sa.Column("assumptions_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_trips_owner_id", "trips", ["owner_id"])
    op.create_index("ix_trips_status", "trips", ["status"])
    op.create_index("ix_trips_vehicle_profile_id", "trips", ["vehicle_profile_id"])
    op.bulk_insert(
        sa.table(
            "vehicle_profiles",
            sa.column("id", sa.String),
            sa.column("version", sa.String),
            sa.column("name", sa.String),
            sa.column("battery_capacity_kwh", sa.Float),
            sa.column("usable_capacity_kwh", sa.Float),
            sa.column("max_charging_power_kw", sa.Float),
            sa.column("connector_type", sa.String),
            sa.column("consumption_curve_json", sa.JSON),
        ),
        [
            {
                "id": "xe-x-mvp-v1",
                "version": "xe-x-mvp-v1",
                "name": "Xe X v1",
                "battery_capacity_kwh": 75.0,
                "usable_capacity_kwh": 71.2,
                "max_charging_power_kw": 150.0,
                "connector_type": "CCS2",
                "consumption_curve_json": {
                    "baseline_wh_per_km": 175,
                    "temperature_c": 25,
                    "payload_kg": 150,
                },
            }
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_trips_vehicle_profile_id", table_name="trips")
    op.drop_index("ix_trips_status", table_name="trips")
    op.drop_index("ix_trips_owner_id", table_name="trips")
    op.drop_table("trips")
    op.drop_table("vehicle_profiles")
