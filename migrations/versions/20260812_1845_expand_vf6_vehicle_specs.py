"""Expand the VF 6 Plus profile with versioned planning and official specs.

Revision ID: 20260812_1845
Revises: 20260809_2330
"""

import sqlalchemy as sa
from alembic import op

revision = "20260812_1845"
down_revision = "20260809_2330"
branch_labels = None
depends_on = None

PROFILE_ID = "vinfast-vf6-plus-v1"
SOURCE_URL = (
    "https://vinfastauto.com/vn_vi/cau-hoi-thuong-gap/"
    "cau-hoi-xe-o-to/san-pham/vf-6"
)


def _vehicle_profiles():
    return sa.table(
        "vehicle_profiles",
        sa.column("id", sa.String),
        sa.column("version", sa.String),
        sa.column("consumption_curve_json", sa.JSON),
    )


def upgrade() -> None:
    profiles = _vehicle_profiles()
    op.get_bind().execute(
        profiles.update()
        .where(profiles.c.id == PROFILE_ID)
        .values(
            version="vinfast_vf6_plus_2025.2",
            consumption_curve_json={
                "baseline_wh_per_km": 156.4,
                "baseline_derivation": (
                    "usable_capacity_kwh / official_WLTP_range_381km"
                ),
                "reference_range_km": 381.0,
                "reference_range_standard": "WLTP",
                "brochure_range_km": 460.0,
                "brochure_range_standard": "NEDC",
                "motor_power_kw": 150.0,
                "max_torque_nm": 310.0,
                "drive_type": "FWD / Cầu trước",
                "seats": 5,
                "curb_weight_kg": 1743.0,
                "dimensions_mm": "4.241 × 1.834 × 1.580",
                "wheelbase_mm": 2730.0,
                "ground_clearance_mm": 170.0,
                "wheel_size_inch": 19.0,
                "fast_charge_10_70_min": 25.0,
                "ambient_temperature_c": 25.0,
                "vehicle_payload_kg": 150.0,
                "terrain": "LIVE_OPEN_METEO_ELEVATION",
                "official_source": SOURCE_URL,
            },
        )
    )


def downgrade() -> None:
    profiles = _vehicle_profiles()
    op.get_bind().execute(
        profiles.update()
        .where(profiles.c.id == PROFILE_ID)
        .values(
            version="vinfast_vf6_plus_2025.1",
            consumption_curve_json={
                "baseline_wh_per_km": 156.4,
                "baseline_derivation": (
                    "usable_capacity_kwh / official_WLTP_range_381km"
                ),
                "curb_weight_kg": 1743.0,
                "ambient_temperature_c": 25.0,
                "vehicle_payload_kg": 150.0,
                "terrain": "LIVE_OPEN_METEO_ELEVATION",
                "official_source": SOURCE_URL,
            },
        )
    )
