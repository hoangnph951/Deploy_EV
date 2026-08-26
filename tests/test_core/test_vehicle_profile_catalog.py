from __future__ import annotations

import json

import pytest

from src.packages.core.trips.infrastructure.vehicle_fixtures import (
    load_vehicle_profile_fixtures,
)


def test_verified_vinfast_catalog_has_complete_energy_inputs():
    profiles = [
        profile
        for profile in load_vehicle_profile_fixtures()
        if profile.id.startswith("vinfast-")
    ]

    assert len(profiles) == 8
    assert len({profile.id for profile in profiles}) == len(profiles)

    for profile in profiles:
        curve = json.loads(profile.consumption_curve_json)
        assert profile.usable_capacity_kwh > 0
        assert profile.max_charging_power_kw > 0
        assert profile.connector_type == "CCS2"
        assert curve["baseline_wh_per_km"] > 0
        assert curve["reference_range_km"] > 0
        assert curve["reference_range_standard"] in {"NEDC", "WLTP"}
        assert curve["curb_weight_kg"] > 0
        assert curve["official_source"].startswith("https://")


@pytest.mark.parametrize(
    ("profile_id", "battery_kwh", "max_dc_kw", "range_km", "standard"),
    [
        ("vinfast-vf3-v1", 18.64, 24.0, 215.0, "NEDC"),
        ("vinfast-vf5-plus-v1", 37.23, 50.0, 326.0, "NEDC"),
        ("vinfast-vf6-plus-v1", 59.6, 100.0, 381.0, "WLTP"),
        ("vinfast-vf7-plus-awd-v1", 75.3, 110.0, 431.0, "WLTP"),
        ("vinfast-vf8-plus-catl-v1", 87.7, 149.0, 457.0, "WLTP"),
    ],
)
def test_catalog_keeps_official_variant_values(
    profile_id: str,
    battery_kwh: float,
    max_dc_kw: float,
    range_km: float,
    standard: str,
):
    profile = next(
        item for item in load_vehicle_profile_fixtures() if item.id == profile_id
    )
    curve = json.loads(profile.consumption_curve_json)

    assert profile.usable_capacity_kwh == battery_kwh
    assert profile.max_charging_power_kw == max_dc_kw
    assert curve["reference_range_km"] == range_km
    assert curve["reference_range_standard"] == standard
