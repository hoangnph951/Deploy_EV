from datetime import UTC, datetime

from src.packages.contracts.trips import (
    AssumptionSnapshot,
    ChargingStopProposal,
)
from src.packages.core.trips.infrastructure.energy_tool import (
    EnergyLegCalculation,
    EnergySimulationResult,
)
from src.packages.core.trips.infrastructure.feasibility_tool import FeasibilityTool


def assumptions(reserve: float = 15.0) -> AssumptionSnapshot:
    return AssumptionSnapshot(
        policy_version="test-policy-v1",
        reserve_soc_percent=reserve,
        ambient_temperature_c=25.0,
        vehicle_payload_kg=150.0,
        vehicle_profile_version="xe_x_v1.0",
        created_at=datetime.now(UTC),
    )


def energy_result(
    arrival_soc: float,
    *,
    stops: list[ChargingStopProposal] | None = None,
    unreachable: bool = False,
) -> EnergySimulationResult:
    return EnergySimulationResult(
        legs=[
            EnergyLegCalculation(
                from_name="Origin",
                to_name="Destination",
                distance_km=100.0,
                energy_consumed_kwh=20.0,
                start_soc_percent=50.0,
                arrival_soc_percent=arrival_soc,
            )
        ],
        charging_stops=stops or [],
        final_arrival_soc_percent=arrival_soc,
        total_energy_kwh=20.0,
        total_charge_time_min=0.0,
        min_soc_encountered=arrival_soc,
        unreachable_next_station=unreachable,
    )


def test_arrival_at_reserve_is_feasible() -> None:
    verdict = FeasibilityTool().evaluate(energy_result(15.0), assumptions(), 50.0)

    assert verdict.is_feasible is True
    assert verdict.verdict == "FEASIBLE"
    assert "SOC_BELOW_RESERVE_15" not in verdict.reason_codes


def test_arrival_below_reserve_is_infeasible() -> None:
    verdict = FeasibilityTool().evaluate(energy_result(14.9), assumptions(), 50.0)

    assert verdict.is_feasible is False
    assert verdict.verdict == "INFEASIBLE"
    assert "SOC_BELOW_RESERVE_15" in verdict.reason_codes


def test_negative_soc_is_explained_as_energy_shortfall_not_physical_soc() -> None:
    verdict = FeasibilityTool().evaluate(energy_result(-1123.0), assumptions(), 23.0)

    assert verdict.is_feasible is False
    assert "-1123.0%" not in " ".join(verdict.reasons)
    assert "Pin sẽ cạn trước khi đến nơi" in " ".join(verdict.reasons)
    assert "20.0 kWh" in " ".join(verdict.reasons)


def test_unreachable_next_station_is_infeasible() -> None:
    verdict = FeasibilityTool().evaluate(energy_result(5.0, unreachable=True), assumptions(), 50.0)

    assert verdict.is_feasible is False
    assert "UNREACHABLE_NEXT_STATION" in verdict.reason_codes


def test_incompatible_connector_is_infeasible() -> None:
    stop = ChargingStopProposal(
        station_id="chademo-only",
        name="CHAdeMO only",
        lat=21.0,
        lon=105.0,
        arrival_soc_percent=20.0,
        departure_soc_percent=80.0,
        charge_duration_min=30.0,
        energy_added_kwh=40.0,
        max_power_kw=50.0,
        connector_type="CHAdeMO",
    )
    verdict = FeasibilityTool().evaluate(energy_result(25.0, stops=[stop]), assumptions(), 50.0)

    assert verdict.is_feasible is False
    assert "NO_COMPATIBLE_CONNECTOR" in verdict.reason_codes


def test_no_compatible_corridor_station_is_infeasible_when_charging_is_required() -> None:
    verdict = FeasibilityTool().evaluate(
        energy_result(10.0, unreachable=True),
        assumptions(),
        50.0,
        no_compatible_connector=True,
    )

    assert verdict.is_feasible is False
    assert "NO_COMPATIBLE_CONNECTOR" in verdict.reason_codes


def test_stale_station_is_risky_not_silently_fresh() -> None:
    stop = ChargingStopProposal(
        station_id="stale-ccs2",
        name="Stale CCS2",
        lat=21.0,
        lon=105.0,
        arrival_soc_percent=20.0,
        departure_soc_percent=80.0,
        charge_duration_min=30.0,
        energy_added_kwh=40.0,
        max_power_kw=50.0,
        connector_type="CCS2",
        freshness="STALE",
    )
    verdict = FeasibilityTool().evaluate(energy_result(25.0, stops=[stop]), assumptions(), 50.0)

    assert verdict.is_feasible is True
    assert verdict.verdict == "RISKY"
    assert "STALE_STATION_DATA" in verdict.reason_codes


def test_unverified_web_station_is_risky_not_silently_official() -> None:
    stop = ChargingStopProposal(
        station_id="web-ccs2",
        name="Web CCS2",
        lat=21.0,
        lon=105.0,
        arrival_soc_percent=20.0,
        departure_soc_percent=80.0,
        charge_duration_min=30.0,
        energy_added_kwh=40.0,
        max_power_kw=50.0,
        connector_type="CCS2",
        freshness="FRESH",
        station_status="UNVERIFIED",
    )
    verdict = FeasibilityTool().evaluate(energy_result(25.0, stops=[stop]), assumptions(), 50.0)

    assert verdict.is_feasible is True
    assert verdict.verdict == "RISKY"
    assert verdict.risk_score == 40
    assert "UNVERIFIED_STATION_DATA" in verdict.reason_codes


def test_detour_distance_limit_has_explicit_reason_code() -> None:
    verdict = FeasibilityTool().evaluate(
        energy_result(10.0, unreachable=True),
        assumptions(),
        50.0,
        detour_distance_exceeded=True,
    )

    assert verdict.is_feasible is False
    assert "DETOUR_DISTANCE_EXCEEDED" in verdict.reason_codes


def test_detour_time_limit_has_explicit_reason_code() -> None:
    verdict = FeasibilityTool().evaluate(
        energy_result(10.0, unreachable=True),
        assumptions(),
        50.0,
        detour_time_exceeded=True,
    )

    assert verdict.is_feasible is False
    assert "DETOUR_TIME_EXCEEDED" in verdict.reason_codes
