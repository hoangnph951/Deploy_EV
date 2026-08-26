import json
from datetime import UTC, datetime

import pytest

from src.packages.contracts.trips import AssumptionSnapshot, DataProvenance, EnvironmentSnapshot
from src.packages.core.trips.domain.entities import VehicleProfile
from src.packages.core.trips.infrastructure.energy_tool import EnergyTool
from src.packages.core.trips.infrastructure.station_service import CandidateStation


def vehicle() -> VehicleProfile:
    return VehicleProfile(
        id="vf6-test",
        version="test-v1",
        name="VinFast VF 6 Plus",
        battery_capacity_kwh=59.6,
        usable_capacity_kwh=59.6,
        max_charging_power_kw=100.0,
        connector_type="CCS2",
        consumption_curve_json=json.dumps(
            {"baseline_wh_per_km": 156.4, "curb_weight_kg": 1743.0}
        ),
    )


def vf3_vehicle() -> VehicleProfile:
    return VehicleProfile(
        id="vf3-test",
        version="test-v1",
        name="VinFast VF 3",
        battery_capacity_kwh=18.64,
        usable_capacity_kwh=18.64,
        max_charging_power_kw=24.0,
        connector_type="CCS2",
        consumption_curve_json=json.dumps(
            {"baseline_wh_per_km": 86.7, "curb_weight_kg": 857.0}
        ),
    )


def assumptions() -> AssumptionSnapshot:
    return AssumptionSnapshot(
        policy_version="test-policy-v1",
        reserve_soc_percent=15.0,
        ambient_temperature_c=22.0,
        vehicle_payload_kg=150.0,
        vehicle_profile_version="test-v1",
        created_at=datetime.now(UTC),
    )


def environment() -> EnvironmentSnapshot:
    provenance = DataProvenance(
        source="TEST_FIXTURE",
        source_url="test://environment",
        retrieved_at=datetime.now(UTC),
    )
    return EnvironmentSnapshot(
        temperature_c=22.0,
        weather_provenance=provenance,
        elevation_provenance=provenance,
    )


def test_environment_fallback_margin_increases_effective_consumption() -> None:
    tool = EnergyTool()
    live_environment = environment()
    fallback_environment = live_environment.model_copy(
        update={"consumption_margin_percent": 20.0}
    )

    live_rate = tool.effective_consumption_rate(
        100.0, vehicle(), assumptions(), live_environment
    )
    fallback_rate = tool.effective_consumption_rate(
        100.0, vehicle(), assumptions(), fallback_environment
    )

    assert fallback_rate == pytest.approx(live_rate * 1.20)


def station(*, progress: float = 0.0, detour: float = 2.0) -> CandidateStation:
    return CandidateStation(
        station_id="backtrack-ccs2",
        name="Trạm CCS2 gần điểm xuất phát",
        lat=21.0,
        lon=105.84,
        address="Hà Nội",
        connector_types=["CCS2"],
        max_power_kw=120.0,
        detour_distance_km=detour,
        detour_duration_min=detour / 40.0 * 60.0,
        freshness="FRESH",
        distance_from_origin_km=progress,
    )


def route_station(progress: float) -> CandidateStation:
    return CandidateStation(
        station_id=f"station-{progress:.0f}",
        name=f"Station {progress:.0f}",
        lat=21.0 - progress / 1000.0,
        lon=105.84,
        address="Test corridor",
        connector_types=["CCS2"],
        max_power_kw=60.0,
        detour_distance_km=0.0,
        detour_duration_min=0.0,
        freshness="FRESH",
        distance_from_origin_km=progress,
    )


def test_station_at_origin_progress_can_be_used_by_low_soc_trip() -> None:
    chains = EnergyTool().find_station_chains(
        total_distance_km=15.42,
        initial_soc_percent=17.0,
        vehicle_profile=vehicle(),
        assumptions=assumptions(),
        candidate_stations=[station()],
        environment=environment(),
    )

    assert chains
    assert chains[0].stations[0].station_id == "backtrack-ccs2"


def test_station_at_origin_with_soc_exactly_at_reserve_is_feasible() -> None:
    result = EnergyTool().simulate_fixed_itinerary(
        leg_distances_km=[0.0, 10.0],
        initial_soc_percent=15.0,
        vehicle_profile=vehicle(),
        assumptions=assumptions(),
        stations=[station(progress=0.0, detour=0.0)],
        environment=environment(),
    )

    assert result.charging_stops[0].arrival_soc_percent == 15.0
    assert result.unreachable_next_station is False
    assert result.final_arrival_soc_percent >= 15.0


def test_backtrack_is_rejected_when_station_arrival_breaks_reserve() -> None:
    chains = EnergyTool().find_station_chains(
        total_distance_km=15.42,
        initial_soc_percent=17.0,
        vehicle_profile=vehicle(),
        assumptions=assumptions(),
        candidate_stations=[station(detour=20.0)],
        environment=environment(),
    )

    assert chains == []


def test_charge_target_can_exceed_eighty_when_next_leg_requires_it() -> None:
    result = EnergyTool().simulate_fixed_itinerary(
        leg_distances_km=[2.0, 300.0],
        initial_soc_percent=30.0,
        vehicle_profile=vehicle(),
        assumptions=assumptions(),
        stations=[station(progress=2.0, detour=0.0)],
        environment=environment(),
    )

    assert result.charging_stops[0].departure_soc_percent > 80.0
    assert result.final_arrival_soc_percent >= 15.0


def test_energy_fixture_is_reproducible_after_excluding_dynamic_identifiers() -> None:
    outputs = []
    for _ in range(10):
        result = EnergyTool().simulate_fixed_itinerary(
            leg_distances_km=[2.0, 120.0],
            initial_soc_percent=35.0,
            vehicle_profile=vehicle(),
            assumptions=assumptions(),
            stations=[station(progress=2.0, detour=0.0)],
            environment=environment(),
        )
        outputs.append(
            {
                "legs": result.legs,
                "station_ids": [stop.station_id for stop in result.charging_stops],
                "soc_points": result.soc_points,
                "final_soc": result.final_arrival_soc_percent,
                "consumption": result.effective_consumption_wh_per_km,
            }
        )

    assert all(output == outputs[0] for output in outputs[1:])


def test_vf3_long_route_search_is_not_capped_at_five_stops() -> None:
    tool = EnergyTool()
    candidate_stations = [route_station(progress) for progress in (100, 250, 400, 550, 700, 850)]
    stop_limit = tool.recommended_search_stop_limit(
        total_distance_km=1000.0,
        initial_soc_percent=70.0,
        vehicle_profile=vf3_vehicle(),
        assumptions=assumptions(),
        environment=environment(),
        candidate_station_count=len(candidate_stations),
    )

    chains = tool.find_station_chains(
        total_distance_km=1000.0,
        initial_soc_percent=70.0,
        vehicle_profile=vf3_vehicle(),
        assumptions=assumptions(),
        candidate_stations=candidate_stations,
        environment=environment(),
        max_stops=stop_limit,
    )

    assert stop_limit == 6
    assert chains
    assert len(chains[0].stations) == 6


def test_station_chain_search_respects_state_expansion_budget() -> None:
    kwargs = {
        "total_distance_km": 300.0,
        "initial_soc_percent": 50.0,
        "vehicle_profile": vehicle(),
        "assumptions": assumptions(),
        "candidate_stations": [route_station(100.0)],
        "environment": environment(),
    }

    limited = EnergyTool().find_station_chains(**kwargs, max_state_expansions=1)
    completed = EnergyTool().find_station_chains(**kwargs, max_state_expansions=2)

    assert limited == []
    assert completed
