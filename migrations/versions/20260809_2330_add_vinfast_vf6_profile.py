"""Add the versioned VinFast VF 6 Plus vehicle profile.

Revision ID: 20260809_2330
Revises: 20260808_1700
"""

import sqlalchemy as sa
from alembic import op

revision = "20260809_2330"
down_revision = "20260808_1700"
branch_labels = None
depends_on = None

PROFILE_ID = "vinfast-vf6-plus-v1"


def upgrade() -> None:
    vehicle_profiles = sa.table(
        "vehicle_profiles",
        sa.column("id", sa.String),
        sa.column("version", sa.String),
        sa.column("name", sa.String),
        sa.column("battery_capacity_kwh", sa.Float),
        sa.column("usable_capacity_kwh", sa.Float),
        sa.column("max_charging_power_kw", sa.Float),
        sa.column("connector_type", sa.String),
        sa.column("consumption_curve_json", sa.JSON),
    )
    connection = op.get_bind()
    values = {
        "version": "vinfast_vf6_plus_2025.1",
        "name": "VinFast VF 6 Plus",
        "battery_capacity_kwh": 59.6,
        "usable_capacity_kwh": 59.6,
        "max_charging_power_kw": 100.0,
        "connector_type": "CCS2",
        "consumption_curve_json": {
            "baseline_wh_per_km": 156.4,
            "baseline_derivation": "usable_capacity_kwh / official_WLTP_range_381km",
            "curb_weight_kg": 1743.0,
            "ambient_temperature_c": 25.0,
            "vehicle_payload_kg": 150.0,
            "terrain": "LIVE_OPEN_METEO_ELEVATION",
            "official_source": (
                "https://vinfastauto.com/vn_vi/cau-hoi-thuong-gap/"
                "cau-hoi-xe-o-to/san-pham/vf-6"
            ),
        },
    }

    exists = connection.scalar(
        sa.select(sa.literal(1)).select_from(vehicle_profiles).where(
            vehicle_profiles.c.id == PROFILE_ID
        )
    )
    if exists:
        connection.execute(
            vehicle_profiles.update()
            .where(vehicle_profiles.c.id == PROFILE_ID)
            .values(**values)
        )
    else:
        connection.execute(vehicle_profiles.insert().values(id=PROFILE_ID, **values))


def downgrade() -> None:
    vehicle_profiles = sa.table(
        "vehicle_profiles",
        sa.column("id", sa.String),
    )
    op.get_bind().execute(
        vehicle_profiles.delete().where(vehicle_profiles.c.id == PROFILE_ID)
    )
