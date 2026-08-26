import json
from datetime import UTC, datetime

from src.packages.contracts.trips import (
    AssumptionSnapshot,
    DataProvenance,
    EnvironmentSnapshot,
)
from src.packages.core.trips.domain.entities import VehicleProfile
from src.packages.core.trips.infrastructure.energy_tool import EnergyTool
from src.packages.core.trips.infrastructure.feasibility_tool import FeasibilityTool
from src.packages.core.trips.infrastructure.station_service import CandidateStation

GOLDEN_TIME = datetime(2026, 8, 22, tzinfo=UTC)


def _vehicle() -> VehicleProfile:
    return VehicleProfile(
        id="vf6-golden",
        version="vf6-golden-v1",
        name="VinFast VF 6 Plus",
        battery_capacity_kwh=59.6,
        usable_capacity_kwh=59.6,
        max_charging_power_kw=100.0,
        connector_type="CCS2",
        consumption_curve_json=json.dumps({"baseline_wh_per_km": 156.4, "curb_weight_kg": 1743.0}),
    )


def _assumptions() -> AssumptionSnapshot:
    return AssumptionSnapshot(
        policy_version="golden-policy-v1",
        reserve_soc_percent=15.0,
        ambient_temperature_c=25.0,
        vehicle_payload_kg=150.0,
        vehicle_profile_version="vf6-golden-v1",
        created_at=GOLDEN_TIME,
    )


def _environment() -> EnvironmentSnapshot:
    provenance = DataProvenance(
        source="TEST_FIXTURE",
        source_url="test://golden-environment",
        retrieved_at=GOLDEN_TIME,
    )
    return EnvironmentSnapshot(
        temperature_c=25.0,
        precipitation_mm=1.5,
        wind_speed_kmh=12.0,
        elevation_gain_m=420.0,
        elevation_loss_m=275.0,
        weather_provenance=provenance,
        elevation_provenance=provenance,
    )


def _station() -> CandidateStation:
    return CandidateStation(
        station_id="station-golden",
        name="Golden CCS2",
        lat=20.0,
        lon=106.0,
        address="Test",
        connector_types=["CCS2"],
        max_power_kw=120.0,
        detour_distance_km=0.0,
        detour_duration_min=0.0,
        freshness="STALE",
        distance_from_origin_km=120.0,
        station_status="BUSY",
    )


def test_f1_energy_soc_charging_and_risk_golden_output() -> None:
    assumptions = _assumptions()
    result = EnergyTool().simulate_fixed_itinerary(
        leg_distances_km=[120.0, 210.0],
        initial_soc_percent=65.0,
        vehicle_profile=_vehicle(),
        assumptions=assumptions,
        stations=[_station()],
        environment=_environment(),
    )
    risk = FeasibilityTool().evaluate(
        result,
        assumptions,
        65.0,
        required_connector="CCS2",
    )

    assert result.effective_consumption_wh_per_km == 171.5
    assert [
        (
            leg.distance_km,
            leg.energy_consumed_kwh,
            leg.start_soc_percent,
            leg.arrival_soc_percent,
        )
        for leg in result.legs
    ] == [
        (120.0, 20.58, 65.0, 30.5),
        (210.0, 36.01, 80.0, 19.6),
    ]
    assert [(point.distance_km, point.soc_percent, point.kind) for point in result.soc_points] == [
        (0.0, 65.0, "ORIGIN"),
        (120.0, 30.5, "ARRIVAL"),
        (120.0, 80.0, "DEPARTURE"),
        (330.0, 19.6, "DESTINATION"),
    ]

    stop = result.charging_stops[0]
    assert stop.arrival_soc_percent == 30.5
    assert stop.departure_soc_percent == 80.0
    assert stop.energy_added_kwh == 29.52
    assert stop.charge_duration_min == 20.8
    assert result.total_energy_kwh == 56.59
    assert result.total_charge_time_min == 20.8
    assert result.final_arrival_soc_percent == 19.6
    assert result.min_soc_encountered == 19.6
    assert result.unreachable_next_station is False

    assert risk.model_dump() == {
        "verdict": "RISKY",
        "level": "HIGH_RISK",
        "is_feasible": True,
        "reasons": [
            "Dữ liệu trạm 'Golden CCS2' đã cũ (>24h); cần kiểm tra trước khi đến.",
            "VinFast đang ghi nhận metadata trạm 'Golden CCS2' là BUSY; đây không phải availability từng cổng.",
            "SOC tại đích (19.6%) đang sát mức dự phòng.",
        ],
        "reason_codes": [
            "STALE_STATION_DATA",
            "STATION_BUSY",
            "TIGHT_ENERGY_MARGIN",
        ],
        "risk_score": 80.0,
    }
