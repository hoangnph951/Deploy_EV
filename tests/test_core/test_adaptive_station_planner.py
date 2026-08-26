import json
from datetime import UTC, datetime

from src.packages.agent.planning.tools.adaptive_station_planner import (
    AdaptiveSearchProfile,
    AdaptiveStationPlanner,
)
from src.packages.contracts.trips import AssumptionSnapshot, DataProvenance, EnvironmentSnapshot
from src.packages.core.trips.domain.entities import VehicleProfile
from src.packages.core.trips.domain.station_graph import StationEdge
from src.packages.core.trips.infrastructure.energy_tool import EnergyTool
from src.packages.core.trips.infrastructure.feasibility_tool import FeasibilityTool
from src.packages.core.trips.infrastructure.routing import RouteSegmentData, RoutingResult
from src.packages.core.trips.infrastructure.station_service import CandidateStation


class LinearRoutingProvider:
    def get_route(self, origin_lat, origin_lng, dest_lat, dest_lng, waypoints=None):
        assert not waypoints
        distance = abs(dest_lng - origin_lng) * 100.0
        return RoutingResult(
            polyline=[[origin_lat, origin_lng], [dest_lat, dest_lng]],
            distance_km=round(distance, 2),
            duration_min=round(distance, 1),
            segments=[
                RouteSegmentData(
                    from_name="Origin",
                    to_name="Destination",
                    distance_km=round(distance, 2),
                    duration_min=round(distance, 1),
                    start_lat=origin_lat,
                    start_lng=origin_lng,
                    end_lat=dest_lat,
                    end_lng=dest_lng,
                )
            ],
            provider="TEST_FIXTURE",
            source_url="test://linear-route",
            retrieved_at=datetime.now(UTC),
        )


class RateLimitedRoutingProvider:
    def __init__(self):
        self.calls = 0

    def get_route(self, *args, **kwargs):
        from src.packages.core.trips.infrastructure.routing import RoutingUnavailableError

        self.calls += 1
        raise RoutingUnavailableError(
            "rate limited",
            http_status=429,
            provider_status="RATE_LIMITED",
            retry_after_seconds=30.0,
        )


class WindowStationService:
    def __init__(self):
        self.official_calls: list[int] = []
        self.recovery_calls: list[int] = []
        self.stations = [_station(progress) for progress in (5, 150, 300, 450, 600, 750, 900)]

    def find_official_station_window(self, **kwargs):
        self.official_calls.append(kwargs["max_detail_candidates"])
        return [
            station
            for station in self.stations
            if kwargs["progress_start_km"]
            <= station.distance_from_origin_km
            <= kwargs["progress_end_km"]
        ]

    def find_recovery_station_window(self, **kwargs):
        self.recovery_calls.append(kwargs["max_detail_candidates"])
        return self.find_official_station_window(**kwargs)


def _station(progress: float) -> CandidateStation:
    return CandidateStation(
        station_id=f"station-{progress}",
        name=f"Station {progress}",
        lat=0.0,
        lon=progress / 100.0,
        address="Test corridor",
        connector_types=["CCS2"],
        max_power_kw=60.0,
        detour_distance_km=0.0,
        detour_duration_min=0.0,
        freshness="FRESH",
        distance_from_origin_km=progress,
        catalog_location_id=int(progress),
    )


def _vehicle() -> VehicleProfile:
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


def _assumptions() -> AssumptionSnapshot:
    return AssumptionSnapshot(
        policy_version="test-policy-v1",
        reserve_soc_percent=15.0,
        ambient_temperature_c=22.0,
        vehicle_payload_kg=150.0,
        vehicle_profile_version="test-v1",
        created_at=datetime.now(UTC),
    )


def _environment() -> EnvironmentSnapshot:
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


def test_long_route_uses_window_backfill_and_more_than_five_stops() -> None:
    routing = LinearRoutingProvider()
    stations = WindowStationService()
    base_route = routing.get_route(0.0, 0.0, 0.0, 10.0)
    result = AdaptiveStationPlanner(
        routing_provider=routing,
        station_service=stations,
        energy_tool=EnergyTool(),
        feasibility_tool=FeasibilityTool(),
    ).plan(
        base_route=base_route,
        origin_lat=0.0,
        origin_lng=0.0,
        destination_lat=0.0,
        destination_lng=10.0,
        origin_name="Hà Nội",
        destination_name="TP.HCM",
        initial_soc_percent=20.0,
        vehicle_profile=_vehicle(),
        assumptions=_assumptions(),
        environment=_environment(),
        search_profiles=(AdaptiveSearchProfile(5.0, 30.0, 45.0),),
    )

    assert result.validated
    assert len(result.validated[0].energy.charging_stops) == 7
    assert [
        stop.station_id for stop in result.validated[0].energy.charging_stops
    ] == [
        "station-5",
        "station-150",
        "station-300",
        "station-450",
        "station-600",
        "station-750",
        "station-900",
    ]
    assert result.validated[0].energy.final_arrival_soc_percent == 33.5
    assert result.validated[0].energy.total_charge_time_min == 262.4
    assert 24 in stations.official_calls
    assert 48 in stations.official_calls
    assert 96 in stations.official_calls
    assert stations.recovery_calls == []


def test_required_charging_stop_builds_full_multi_stop_chain() -> None:
    routing = LinearRoutingProvider()
    stations = WindowStationService()
    base_route = routing.get_route(0.0, 0.0, 0.0, 10.0)
    result = AdaptiveStationPlanner(
        routing_provider=routing,
        station_service=stations,
        energy_tool=EnergyTool(),
        feasibility_tool=FeasibilityTool(),
    ).plan(
        base_route=base_route,
        origin_lat=0.0,
        origin_lng=0.0,
        destination_lat=0.0,
        destination_lng=10.0,
        origin_name="Hà Nội",
        destination_name="TP.HCM",
        initial_soc_percent=20.0,
        vehicle_profile=_vehicle(),
        assumptions=_assumptions(),
        environment=_environment(),
        search_profiles=(AdaptiveSearchProfile(5.0, 30.0, 45.0),),
        require_charging_stop=True,
    )

    assert result.validated
    stops = result.validated[0].energy.charging_stops
    assert len(stops) == 7
    assert [stop.station_id for stop in stops] == [
        "station-5",
        "station-150",
        "station-300",
        "station-450",
        "station-600",
        "station-750",
        "station-900",
    ]


def test_recovery_source_is_only_used_when_explicitly_requested() -> None:
    routing = LinearRoutingProvider()
    stations = WindowStationService()
    base_route = routing.get_route(0.0, 0.0, 0.0, 10.0)
    planner = AdaptiveStationPlanner(
        routing_provider=routing,
        station_service=stations,
        energy_tool=EnergyTool(),
        feasibility_tool=FeasibilityTool(),
    )
    common = dict(
        base_route=base_route,
        origin_lat=0.0,
        origin_lng=0.0,
        destination_lat=0.0,
        destination_lng=10.0,
        origin_name="Hà Nội",
        destination_name="TP.HCM",
        initial_soc_percent=20.0,
        vehicle_profile=_vehicle(),
        assumptions=_assumptions(),
        environment=_environment(),
        search_profiles=(AdaptiveSearchProfile(5.0, 30.0, 45.0),),
    )

    planner.plan(**common, source="OFFICIAL")
    assert stations.recovery_calls == []
    planner.plan(**common, source="RECOVERY")
    assert stations.recovery_calls


def test_rate_limit_stops_edge_validation_immediately() -> None:
    stations = WindowStationService()
    routing = RateLimitedRoutingProvider()
    base_route = LinearRoutingProvider().get_route(0.0, 0.0, 0.0, 10.0)
    result = AdaptiveStationPlanner(
        routing_provider=routing,
        station_service=stations,
        energy_tool=EnergyTool(),
        feasibility_tool=FeasibilityTool(),
    ).plan(
        base_route=base_route,
        origin_lat=0.0,
        origin_lng=0.0,
        destination_lat=0.0,
        destination_lng=10.0,
        origin_name="Hà Nội",
        destination_name="TP.HCM",
        initial_soc_percent=20.0,
        vehicle_profile=_vehicle(),
        assumptions=_assumptions(),
        environment=_environment(),
        search_profiles=(AdaptiveSearchProfile(5.0, 30.0, 45.0),),
    )

    assert result.routing_rate_limited is True
    assert result.retry_after_seconds == 30.0
    assert routing.calls == 1


class RecordingLinearRoutingProvider(LinearRoutingProvider):
    def __init__(self):
        self.calls: list[tuple[float, float, float, float]] = []

    def get_route(self, origin_lat, origin_lng, dest_lat, dest_lng, waypoints=None):
        self.calls.append((origin_lat, origin_lng, dest_lat, dest_lng))
        return super().get_route(origin_lat, origin_lng, dest_lat, dest_lng, waypoints)


class ExactFixtureEdgeRepository:
    def __init__(self):
        self.hits = 0
        self.writes: list[StationEdge] = []

    def get_edge(self, from_id, to_id, routing_provider, road_version):
        if routing_provider != "TEST_FIXTURE" or road_version != "fixture-road-v1":
            return None
        self.hits += 1
        retrieved_at = datetime.now(UTC)
        return StationEdge(
            from_location_id=from_id,
            to_location_id=to_id,
            routing_provider="TEST_FIXTURE",
            routing_profile="car",
            road_version="fixture-road-v1",
            distance_km=round(abs(to_id - from_id), 2),
            duration_minutes=round(abs(to_id - from_id), 1),
            geometry_polyline=json.dumps(
                [[0.0, from_id / 100.0], [0.0, to_id / 100.0]]
            ),
            provider_source_url="test://linear-route",
            provider_retrieved_at=retrieved_at,
            computed_at=retrieved_at,
        )

    def upsert_edge(self, edge):
        self.writes.append(edge)

    def neighbors(self, location_id, routing_provider, road_version):
        return []


def test_exact_station_graph_edges_preserve_planner_output() -> None:
    common = dict(
        base_route=LinearRoutingProvider().get_route(0.0, 0.0, 0.0, 10.0),
        origin_lat=0.0,
        origin_lng=0.0,
        destination_lat=0.0,
        destination_lng=10.0,
        origin_name="Origin",
        destination_name="Destination",
        initial_soc_percent=20.0,
        vehicle_profile=_vehicle(),
        assumptions=_assumptions(),
        environment=_environment(),
        search_profiles=(AdaptiveSearchProfile(5.0, 30.0, 45.0),),
    )
    live_routing = RecordingLinearRoutingProvider()
    live = AdaptiveStationPlanner(
        routing_provider=live_routing,
        station_service=WindowStationService(),
        energy_tool=EnergyTool(),
        feasibility_tool=FeasibilityTool(),
    ).plan(**common)

    graph_routing = RecordingLinearRoutingProvider()
    edges = ExactFixtureEdgeRepository()
    graph = AdaptiveStationPlanner(
        routing_provider=graph_routing,
        station_service=WindowStationService(),
        energy_tool=EnergyTool(),
        feasibility_tool=FeasibilityTool(),
        station_edge_repository=edges,
        station_graph_enabled=True,
        station_graph_routing_provider="TEST_FIXTURE",
        station_graph_road_version="fixture-road-v1",
    ).plan(**common)

    assert [stop.station_id for stop in graph.validated[0].energy.charging_stops] == [
        stop.station_id for stop in live.validated[0].energy.charging_stops
    ]
    assert graph.validated[0].energy == live.validated[0].energy
    assert edges.hits > 0
    assert len(graph_routing.calls) < len(live_routing.calls)
    assert any(call[1] == 0.0 for call in graph_routing.calls)  # origin is never a graph node
    assert any(call[3] == 10.0 for call in graph_routing.calls)  # destination stays live-routed
