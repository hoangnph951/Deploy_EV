from __future__ import annotations

import json
from pathlib import Path

from src.packages.core.trips.domain.entities import VehicleProfile

_FIXTURE_PATH = Path(__file__).with_name("fixtures") / "vehicle_profiles.json"


def load_vehicle_profile_fixtures() -> tuple[VehicleProfile, ...]:
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("Vehicle profile fixture must contain at least one profile.")

    profiles: list[VehicleProfile] = []
    for item in payload:
        profiles.append(
            VehicleProfile(
                id=str(item["id"]),
                version=str(item["version"]),
                name=str(item["name"]),
                battery_capacity_kwh=float(item["battery_capacity_kwh"]),
                usable_capacity_kwh=float(item["usable_capacity_kwh"]),
                max_charging_power_kw=float(item["max_charging_power_kw"]),
                connector_type=str(item["connector_type"]),
                consumption_curve_json=json.dumps(item["consumption_curve"]),
            )
        )
    return tuple(profiles)
