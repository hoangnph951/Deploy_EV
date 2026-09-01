import json
from datetime import UTC, datetime

import pytest

from src.packages.agent.planning.nodes.planning_nodes import (
    configure_planning_providers,
    no_feasible_plan_node,
    station_energy_node,
)
from src.packages.contracts.trips import AssumptionSnapshot
from src.packages.core.trips.domain.entities import VehicleProfile
from src.packages.core.trips.infrastructure.environment import StaticEnvironmentProvider
from src.packages.core.trips.infrastructure.routing import (
    InMemoryRoutingProvider,
    RouteSegmentData,
    RoutingResult,
)
from src.packages.core.trips.infrastructure.station_service import (
    CandidateStation,
    FixtureStationDataService,
)


class OneStationService:
    def find_corridor_stations(self, *args, **kwargs):
        return [
            CandidateStation(
                station_id="detour-station",
                name="Trạm kiểm tra detour",
                lat=21.1,
                lon=105.9,
                address="Fixture",
                connector_types=["CCS2"],
                max_power_kw=120.0,
                detour_distance_km=0.0,
                detour_duration_min=0.0,
                freshness="FRESH",
                distance_from_origin_km=20.0,
            )
        ]


class ExpandingStationService:
    def __init__(self):
        self.searches: list[tuple[float, float]] = []

    def find_corridor_stations(self, *args, **kwargs):
        corridor_km = kwargs["max_corridor_buffer_km"]
        detour_min = kwargs["max_detour_min"]
        self.searches.append((corridor_km, detour_min))
        if corridor_km < 10.0:
            return []
        return [
            CandidateStation(
                station_id="expanded-station",
                name="Expanded station",
                lat=21.1,
                lon=105.9,
                address="Fixture",
                connector_types=["CCS2"],
                max_power_kw=120.0,
                detour_distance_km=12.0,
                detour_duration_min=18.0,
                freshness="FRESH",
                distance_from_origin_km=20.0,
            )
        ]


class TwoStationService:
    def find_corridor_stations(self, *args, **kwargs):
        return [
            CandidateStation(
                station_id="station-1",
                name="Station 1",
                lat=20.8,
                lon=105.8,
                address="Fixture 1",
                connector_types=["CCS2"],
                max_power_kw=120.0,
                detour_distance_km=4.0,
                detour_duration_min=6.0,
                freshness="FRESH",
                distance_from_origin_km=20.0,
            ),
            CandidateStation(
                station_id="station-2",
                name="Station 2",
                lat=18.8,
                lon=105.8,
                address="Fixture 2",
                connector_types=["CCS2"],
                max_power_kw=120.0,
                detour_distance_km=4.0,
                detour_duration_min=6.0,
                freshness="FRESH",
                distance_from_origin_km=250.0,
            ),
        ]


class EmptyStationService:
    def find_corridor_stations(self, *args, **kwargs):
        return []


class DetourRoutingProvider:
    def __init__(self, *, distance_km: float, duration_min: float):
        self.distance_km = distance_km
        self.duration_min = duration_min

    def get_route(self, origin_lat, origin_lng, dest_lat, dest_lng, waypoints=None):
        assert waypoints
        first_distance = 20.0
        first_duration = min(20.0, self.duration_min)
        return RoutingResult(
            polyline=[[origin_lat, origin_lng], [21.1, 105.9], [dest_lat, dest_lng]],
            distance_km=self.distance_km,
            duration_min=self.duration_min,
            segments=[
                RouteSegmentData(
                    from_name="Origin",
                    to_name="Station",
                    distance_km=first_distance,
                    duration_min=first_duration,
                    start_lat=origin_lat,
                    start_lng=origin_lng,
                    end_lat=21.1,
                    end_lng=105.9,
                ),
                RouteSegmentData(
                    from_name="Station",
                    to_name="Destination",
                    distance_km=self.distance_km - first_distance,
                    duration_min=self.duration_min - first_duration,
                    start_lat=21.1,
                    start_lng=105.9,
                    end_lat=dest_lat,
                    end_lng=dest_lng,
                ),
            ],
            provider="TEST_FIXTURE",
            source_url="test://detour",
            retrieved_at=datetime.now(UTC),
        )


class MultiStopRoutingProvider:
    def get_route(self, origin_lat, origin_lng, dest_lat, dest_lng, waypoints=None):
        assert waypoints and len(waypoints) == 2
        stops = [(origin_lat, origin_lng), *waypoints, (dest_lat, dest_lng)]
        distances = [20.0, 248.0, 250.0]
        durations = [20.0, 250.0, 255.0]
        return RoutingResult(
            polyline=[[lat, lng] for lat, lng in stops],
            distance_km=sum(distances),
            duration_min=sum(durations),
            segments=[
                RouteSegmentData(
                    from_name=f"Stop {index}",
                    to_name=f"Stop {index + 1}",
                    distance_km=distance,
                    duration_min=durations[index],
                    start_lat=stops[index][0],
                    start_lng=stops[index][1],
                    end_lat=stops[index + 1][0],
                    end_lng=stops[index + 1][1],
                )
                for index, distance in enumerate(distances)
            ],
            provider="TEST_FIXTURE",
            source_url="test://multi-stop-detour",
            retrieved_at=datetime.now(UTC),
        )


def _state() -> dict:
    vehicle = VehicleProfile(
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
    assumptions = AssumptionSnapshot(
        policy_version="test-policy-v1",
        reserve_soc_percent=15.0,
        ambient_temperature_c=22.0,
        vehicle_payload_kg=150.0,
        vehicle_profile_version="test-v1",
        created_at=datetime.now(UTC),
    )
    return {
        "origin_lat": 21.0,
        "origin_lng": 105.8,
        "destination_lat": 20.2,
        "destination_lng": 105.8,
        "initial_soc_percent": 35.0,
        "vehicle_profile": vehicle,
        "assumptions": assumptions,
        "route_result": RoutingResult(
            polyline=[[21.0, 105.8], [20.2, 105.8]],
            distance_km=100.0,
            duration_min=100.0,
            segments=[
                RouteSegmentData(
                    from_name="Origin",
                    to_name="Destination",
                    distance_km=100.0,
                    duration_min=100.0,
                    start_lat=21.0,
                    start_lng=105.8,
                    end_lat=20.2,
                    end_lng=105.8,
                )
            ],
            provider="TEST_FIXTURE",
            source_url="test://direct",
            retrieved_at=datetime.now(UTC),
        ),
    }


def _long_state() -> dict:
    state = _state()
    state["destination_lat"] = 16.5
    state["route_result"] = RoutingResult(
        polyline=[[21.0, 105.8], [16.5, 105.8]],
        distance_km=500.0,
        duration_min=500.0,
        segments=[
            RouteSegmentData(
                from_name="Origin",
                to_name="Destination",
                distance_km=500.0,
                duration_min=500.0,
                start_lat=21.0,
                start_lng=105.8,
                end_lat=16.5,
                end_lng=105.8,
            )
        ],
        provider="TEST_FIXTURE",
        source_url="test://long-direct",
        retrieved_at=datetime.now(UTC),
    )
    return state


@pytest.mark.parametrize(
    ("distance_km", "duration_min", "expected_code"),
    [
        (110.01, 114.0, "DETOUR_DISTANCE_EXCEEDED"),
        (108.0, 115.1, "DETOUR_TIME_EXCEEDED"),
    ],
)
def test_planner_reports_exact_detour_rejection(
    distance_km: float, duration_min: float, expected_code: str
) -> None:
    configure_planning_providers(
        routing_provider=DetourRoutingProvider(
            distance_km=distance_km, duration_min=duration_min
        ),
        station_service=OneStationService(),
        environment_provider=StaticEnvironmentProvider(),
    )
    try:
        result = station_energy_node(_state())
    finally:
        configure_planning_providers(
            routing_provider=InMemoryRoutingProvider(),
            station_service=FixtureStationDataService(),
            environment_provider=StaticEnvironmentProvider(),
        )

    assert result["feasibility_verdict"].is_feasible is False
    assert expected_code in result["feasibility_verdict"].reason_codes


def test_planner_expands_station_search_when_near_corridor_has_no_safe_chain() -> None:
    station_service = ExpandingStationService()
    configure_planning_providers(
        routing_provider=DetourRoutingProvider(distance_km=108.0, duration_min=114.0),
        station_service=station_service,
        environment_provider=StaticEnvironmentProvider(),
    )
    try:
        result = station_energy_node(_state())
    finally:
        configure_planning_providers(
            routing_provider=InMemoryRoutingProvider(),
            station_service=FixtureStationDataService(),
            environment_provider=StaticEnvironmentProvider(),
        )

    assert station_service.searches == [(5.0, 15.0), (10.0, 30.0)]
    assert result["feasibility_verdict"].is_feasible is True
    assert [stop.station_id for stop in result["energy_result"].charging_stops] == [
        "expanded-station"
    ]


def test_multi_stop_route_scales_detour_budget_per_charging_stop() -> None:
    state = _long_state()
    configure_planning_providers(
        routing_provider=MultiStopRoutingProvider(),
        station_service=TwoStationService(),
        environment_provider=StaticEnvironmentProvider(),
    )
    try:
        result = station_energy_node(state)
    finally:
        configure_planning_providers(
            routing_provider=InMemoryRoutingProvider(),
            station_service=FixtureStationDataService(),
            environment_provider=StaticEnvironmentProvider(),
        )

    assert result["feasibility_verdict"].is_feasible is True
    assert len(result["energy_result"].charging_stops) == 2
    assert result["route_result"].distance_km - state["route_result"].distance_km == 18.0
    assert result["route_result"].duration_min - state["route_result"].duration_min == 25.0


def test_infeasible_long_route_does_not_recommend_impossible_full_charge() -> None:
    state = _long_state()
    configure_planning_providers(
        routing_provider=InMemoryRoutingProvider(),
        station_service=EmptyStationService(),
        environment_provider=StaticEnvironmentProvider(),
    )
    try:
        energy_result = station_energy_node(state)
        outcome = no_feasible_plan_node({**state, **energy_result})["no_feasible_plan"]
    finally:
        configure_planning_providers(
            routing_provider=InMemoryRoutingProvider(),
            station_service=FixtureStationDataService(),
            environment_provider=StaticEnvironmentProvider(),
        )

    assert outcome.minimum_initial_soc_percent is None
    assert "Không thể đi thẳng" in outcome.suggestions[0]
    assert outcome.search_scope == "ADAPTIVE_CORRIDOR_5_10_20_KM"
    assert outcome.direct_route_distance_km is not None
    assert outcome.estimated_energy_required_kwh is not None
    assert outcome.estimated_reachable_distance_km is not None
    assert outcome.estimated_reachable_distance_km < outcome.direct_route_distance_km
    assert outcome.available_energy_before_reserve_kwh is not None
    assert outcome.energy_shortfall_kwh is not None
    assert outcome.energy_shortfall_kwh > 0
    assert outcome.estimated_minimum_charging_stops is not None
    assert outcome.estimated_minimum_charging_stops > 0
    assert outcome.vehicle_profile_name is not None
    assert outcome.usable_battery_kwh is not None
