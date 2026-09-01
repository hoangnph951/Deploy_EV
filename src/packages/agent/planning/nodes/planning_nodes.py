from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import uuid4

from src.packages.agent.planning.runtime import (
    PlanningRuntime,
    emit_planning_progress,
    get_planning_runtime,
    set_legacy_runtime,
)
from src.packages.agent.planning.state import AgentState
from src.packages.agent.planning.tools.adaptive_station_planner import (
    AdaptiveSearchProfile,
    AdaptiveStationPlanner,
)
from src.packages.contracts.trips import (
    DataProvenance,
    NoFeasiblePlan,
    PlanProposal,
    RouteGeometry,
    RouteSegment,
)
from src.packages.core.trips.infrastructure.energy_tool import EnergyTool
from src.packages.core.trips.infrastructure.environment import EnvironmentProvider
from src.packages.core.trips.infrastructure.feasibility_tool import FeasibilityTool
from src.packages.core.trips.infrastructure.routing import RoutingProvider, RoutingUnavailableError
from src.packages.core.trips.infrastructure.station_service import StationService


@dataclass(frozen=True)
class StationSearchProfile:
    corridor_buffer_km: float
    detour_distance_per_stop_km: float
    detour_duration_per_stop_min: float


# Detour is a soft planning preference. The agent expands it only when the
# preceding corridor cannot produce a route that passes the hard SOC checks.
_STATION_SEARCH_PROFILES = (
    StationSearchProfile(5.0, 10.0, 15.0),
    StationSearchProfile(10.0, 20.0, 30.0),
    StationSearchProfile(20.0, 30.0, 45.0),
)


def set_routing_provider(provider: RoutingProvider) -> None:
    set_legacy_runtime(get_planning_runtime().with_routing_provider(provider))
    _clear_cached_trip_service()


def configure_planning_providers(
    *,
    routing_provider: RoutingProvider,
    station_service: StationService,
    environment_provider: EnvironmentProvider,
) -> None:
    set_legacy_runtime(
        PlanningRuntime(
            routing_provider=routing_provider,
            station_service=station_service,
            environment_provider=environment_provider,
            energy_tool=EnergyTool(),
            feasibility_tool=FeasibilityTool(),
            plan_ranker=get_planning_runtime().plan_ranker,
        )
    )
    _clear_cached_trip_service()


def _clear_cached_trip_service() -> None:
    """Compatibility hook for legacy tests that replace providers at runtime."""
    try:
        from src.packages.core.trips.api.dependencies import get_trip_service

        get_trip_service.cache_clear()
    except (AttributeError, ImportError):
        pass


def routing_node(state: AgentState) -> dict:
    """Fetch a validated route; provider errors intentionally propagate."""
    if "origin_lat" not in state or "destination_lat" not in state:
        return {
            "response": "AI EV Agent sẵn sàng lập kế hoạch hành trình và sạc.",
            "analysis": "Workflow deterministic: routing, station, energy, feasibility.",
        }

    emit_planning_progress("Đang lấy tuyến thực tế từ Goong Directions")
    runtime = get_planning_runtime()
    result = runtime.routing_provider.get_route(
        state["origin_lat"],
        state["origin_lng"],
        state["destination_lat"],
        state["destination_lng"],
    )
    return {"route_result": result}


def station_energy_node(state: AgentState) -> dict:
    if "route_result" not in state or "vehicle_profile" not in state or "assumptions" not in state:
        return {}

    emit_planning_progress("Đang tìm trạm sạc phù hợp và xác minh từng chặng")
    runtime = get_planning_runtime()
    route_result = state["route_result"]
    vehicle_profile = state["vehicle_profile"]
    emit_planning_progress("Đang lấy dữ liệu thời tiết và độ cao từ Open-Meteo")
    environment = runtime.environment_provider.get_snapshot(
        route_result.polyline,
        fallback_temperature_c=state["assumptions"].ambient_temperature_c,
    )
    initial_soc = state.get("initial_soc_percent", 80.0)
    excluded_station_ids = set(state.get("excluded_station_ids", []))

    direct_energy = runtime.energy_tool.simulate_trip_soc(
        total_distance_km=route_result.distance_km,
        initial_soc_percent=initial_soc,
        vehicle_profile=vehicle_profile,
        assumptions=state["assumptions"],
        candidate_stations=[],
        environment=environment,
    )
    direct_verdict = runtime.feasibility_tool.evaluate(
        energy_result=direct_energy,
        assumptions=state["assumptions"],
        initial_soc_percent=initial_soc,
        required_connector=vehicle_profile.connector_type,
        no_compatible_connector=False,
    )
    if direct_verdict.is_feasible:
        return {
            "candidate_stations": [],
            "no_compatible_connector": False,
            "detour_distance_exceeded": False,
            "detour_time_exceeded": False,
            "energy_result": direct_energy,
            "route_result": route_result,
            "feasibility_verdict": direct_verdict,
            "environment": environment,
            "route_energy_alternatives": [],
            "station_provider_unavailable": False,
            "station_route_validation_failed": False,
            "station_routing_rate_limited": False,
            "routing_retry_after_seconds": None,
            "station_routing_budget_exhausted": False,
        }

    # Avoid station-provider calls when the direct route already satisfies the
    # reserve-SOC policy. This also keeps short trips available if station
    # discovery is temporarily unavailable.
    direct_energy = runtime.energy_tool.simulate_fixed_itinerary(
        leg_distances_km=[route_result.distance_km],
        initial_soc_percent=initial_soc,
        vehicle_profile=vehicle_profile,
        assumptions=state["assumptions"],
        stations=[],
        environment=environment,
    )
    direct_verdict = runtime.feasibility_tool.evaluate(
        energy_result=direct_energy,
        assumptions=state["assumptions"],
        initial_soc_percent=initial_soc,
        required_connector=vehicle_profile.connector_type,
        no_compatible_connector=False,
    )
    if direct_verdict.is_feasible:
        return {
            "candidate_stations": [],
            "no_compatible_connector": False,
            "detour_distance_exceeded": False,
            "detour_time_exceeded": False,
            "energy_result": direct_energy,
            "route_result": route_result,
            "feasibility_verdict": direct_verdict,
            "environment": environment,
            "environment_degraded": environment.is_degraded,
            "route_energy_alternatives": [],
            "station_provider_unavailable": False,
            "station_route_validation_failed": False,
            "station_routing_rate_limited": False,
            "routing_retry_after_seconds": None,
            "station_routing_budget_exhausted": False,
        }

    stations_by_id = {}
    validated: list[dict] = []
    route_failures = 0
    tested_chain_ids: set[tuple[str, ...]] = set()
    detour_distance_exceeded = False
    detour_time_exceeded = False
    adaptive_supported = callable(
        getattr(runtime.station_service, "find_station_window", None)
    ) or callable(getattr(runtime.station_service, "find_official_station_window", None))
    if adaptive_supported:
        adaptive_result = AdaptiveStationPlanner(
            routing_provider=runtime.routing_provider,
            station_service=runtime.station_service,
            energy_tool=runtime.energy_tool,
            feasibility_tool=runtime.feasibility_tool,
            station_edge_repository=runtime.station_edge_repository,
            station_graph_enabled=runtime.station_graph_enabled,
            station_graph_routing_provider=runtime.station_graph_routing_provider,
            station_graph_routing_profile=runtime.station_graph_routing_profile,
            station_graph_road_version=runtime.station_graph_road_version,
            station_graph_edge_max_age_seconds=runtime.station_graph_edge_max_age_seconds,
        ).plan(
            base_route=route_result,
            origin_lat=state["origin_lat"],
            origin_lng=state["origin_lng"],
            destination_lat=state["destination_lat"],
            destination_lng=state["destination_lng"],
            origin_name=state.get("origin_name", "Origin"),
            destination_name=state.get("destination_name", "Destination"),
            initial_soc_percent=initial_soc,
            vehicle_profile=vehicle_profile,
            assumptions=state["assumptions"],
            environment=environment,
            search_profiles=tuple(
                AdaptiveSearchProfile(
                    corridor_buffer_km=profile.corridor_buffer_km,
                    detour_distance_per_stop_km=profile.detour_distance_per_stop_km,
                    detour_duration_per_stop_min=profile.detour_duration_per_stop_min,
                )
                for profile in _STATION_SEARCH_PROFILES
            ),
            source="OFFICIAL",
            require_charging_stop=True,
        )
        for station in adaptive_result.discovered_stations:
            if station.station_id in excluded_station_ids:
                continue
            stations_by_id.setdefault(station.station_id, station)
        validated.extend(
            {
                "route": item.route,
                "energy": item.energy,
                "verdict": item.verdict,
                "base_route": item.base_route,
                "includes_backtracking": item.includes_backtracking,
            }
            for item in adaptive_result.validated
            if not excluded_station_ids.intersection(
                stop.station_id for stop in item.energy.charging_stops
            )
        )
        route_failures = adaptive_result.route_failure_count
        station_provider_unavailable = adaptive_result.provider_unavailable
        station_route_validation_failed = bool(
            adaptive_result.attempted_edge_count
            and adaptive_result.route_failure_count == adaptive_result.attempted_edge_count
        )
        station_routing_rate_limited = adaptive_result.routing_rate_limited
        routing_retry_after_seconds = adaptive_result.retry_after_seconds
        station_routing_budget_exhausted = adaptive_result.routing_budget_exhausted
    else:
        station_provider_unavailable = False
        station_route_validation_failed = False
        station_routing_rate_limited = False
        routing_retry_after_seconds = None
        station_routing_budget_exhausted = False

    # The adaptive window search is preferred, but it may discover stations
    # without validating a complete chain (for example after a transient leg
    # failure). Re-run the deterministic corridor chain builder as a fallback
    # instead of immediately declaring the trip infeasible.
    legacy_profiles = (
        _STATION_SEARCH_PROFILES
        if not validated
        and not adaptive_supported
        and callable(getattr(runtime.station_service, "find_corridor_stations", None))
        else ()
    )
    for search_profile in legacy_profiles:
        discovered = runtime.station_service.find_corridor_stations(
            polyline=route_result.polyline,
            origin_lat=state["origin_lat"],
            origin_lng=state["origin_lng"],
            dest_lat=state["destination_lat"],
            dest_lng=state["destination_lng"],
            max_corridor_buffer_km=search_profile.corridor_buffer_km,
            max_detour_min=search_profile.detour_duration_per_stop_min,
            required_connector=vehicle_profile.connector_type,
            total_route_distance_km=route_result.distance_km,
            origin_name=state.get("origin_name", "Origin"),
            dest_name=state.get("destination_name", "Destination"),
        )
        for station in discovered:
            if station.station_id in excluded_station_ids:
                continue
            stations_by_id.setdefault(station.station_id, station)
        stations = sorted(
            stations_by_id.values(), key=lambda station: station.distance_from_origin_km
        )
        max_stops = runtime.energy_tool.recommended_search_stop_limit(
            total_distance_km=route_result.distance_km,
            initial_soc_percent=initial_soc,
            vehicle_profile=vehicle_profile,
            assumptions=state["assumptions"],
            environment=environment,
            candidate_station_count=len(stations),
        )

        chains = runtime.energy_tool.find_station_chains(
            total_distance_km=route_result.distance_km,
            initial_soc_percent=initial_soc,
            vehicle_profile=vehicle_profile,
            assumptions=state["assumptions"],
            candidate_stations=stations,
            environment=environment,
            max_results=24,
            max_stops=max_stops,
        )
        for chain in chains:
            selected_stations = chain.stations
            chain_id = tuple(station.station_id for station in selected_stations)
            if chain_id in tested_chain_ids:
                continue
            tested_chain_ids.add(chain_id)
            try:
                candidate_route = runtime.routing_provider.get_route(
                    state["origin_lat"],
                    state["origin_lng"],
                    state["destination_lat"],
                    state["destination_lng"],
                    waypoints=[(station.lat, station.lon) for station in selected_stations],
                )
            except RoutingUnavailableError:
                route_failures += 1
                continue

            if len(candidate_route.segments) != len(selected_stations) + 1:
                route_failures += 1
                continue
            stop_count = len(selected_stations)
            actual_detour_km = max(0.0, candidate_route.distance_km - route_result.distance_km)
            actual_detour_min = max(0.0, candidate_route.duration_min - route_result.duration_min)
            distance_budget_km = search_profile.detour_distance_per_stop_km * stop_count
            duration_budget_min = search_profile.detour_duration_per_stop_min * stop_count
            if actual_detour_km > distance_budget_km or actual_detour_min > duration_budget_min:
                detour_distance_exceeded = (
                    detour_distance_exceeded or actual_detour_km > distance_budget_km
                )
                detour_time_exceeded = (
                    detour_time_exceeded or actual_detour_min > duration_budget_min
                )
                continue

            cumulative_distance = 0.0
            exact_stations = []
            for index, station in enumerate(selected_stations):
                cumulative_distance += candidate_route.segments[index].distance_km
                exact_stations.append(
                    replace(station, distance_from_origin_km=round(cumulative_distance, 2))
                )
            energy_sim = runtime.energy_tool.simulate_fixed_itinerary(
                leg_distances_km=[segment.distance_km for segment in candidate_route.segments],
                initial_soc_percent=initial_soc,
                vehicle_profile=vehicle_profile,
                assumptions=state["assumptions"],
                stations=exact_stations,
                environment=environment,
            )
            verdict = runtime.feasibility_tool.evaluate(
                energy_result=energy_sim,
                assumptions=state["assumptions"],
                initial_soc_percent=initial_soc,
                required_connector=vehicle_profile.connector_type,
                no_compatible_connector=False,
            )
            if verdict.is_feasible:
                validated.append(
                    {
                        "route": candidate_route,
                        "energy": energy_sim,
                        "verdict": verdict,
                        "base_route": route_result,
                        "includes_backtracking": bool(
                            selected_stations
                            and selected_stations[0].distance_from_origin_km <= 0.25
                        ),
                    }
                )

        if validated:
            break

    stations = sorted(
        stations_by_id.values(), key=lambda station: station.distance_from_origin_km
    )
    if not validated and tested_chain_ids and route_failures == len(tested_chain_ids):
        raise RoutingUnavailableError(
            "Goong could not validate any candidate route through the selected chargers."
        )

    def total_minutes(item: dict) -> float:
        return item["route"].duration_min + item["energy"].total_charge_time_min

    ordered: list[dict] = []
    if validated:
        balanced = min(
            validated,
            key=lambda item: (
                -len(item["energy"].charging_stops),
                total_minutes(item) + max(0.0, item["route"].distance_km - route_result.distance_km),
                -item["energy"].min_soc_encountered,
            ),
        )
        fastest = min(
            validated,
            key=lambda item: (-len(item["energy"].charging_stops), total_minutes(item)),
        )
        safest = max(
            validated,
            key=lambda item: (
                len(item["energy"].charging_stops),
                item["energy"].min_soc_encountered,
                -max(0.0, item["route"].distance_km - route_result.distance_km),
            ),
        )
        for strategy, item in (("BALANCED", balanced), ("FASTEST", fastest), ("SAFEST", safest)):
            identity = tuple(stop.station_id for stop in item["energy"].charging_stops)
            if any(
                tuple(stop.station_id for stop in existing["energy"].charging_stops) == identity
                for existing in ordered
            ):
                continue
            ordered.append({**item, "strategy": strategy})
        for item in sorted(validated, key=total_minutes):
            if len(ordered) >= 3:
                break
            identity = tuple(stop.station_id for stop in item["energy"].charging_stops)
            if any(
                tuple(stop.station_id for stop in existing["energy"].charging_stops) == identity
                for existing in ordered
            ):
                continue
            ordered.append({**item, "strategy": "BALANCED"})

    if ordered:
        selected = ordered[0]
        energy_sim = selected["energy"]
        selected_route = selected["route"]
        verdict = selected["verdict"]
    else:
        energy_sim = runtime.energy_tool.simulate_trip_soc(
            total_distance_km=route_result.distance_km,
            initial_soc_percent=state.get("initial_soc_percent", 80.0),
            vehicle_profile=vehicle_profile,
            assumptions=state["assumptions"],
            candidate_stations=[],
            environment=environment,
        )
        selected_route = route_result
        verdict = runtime.feasibility_tool.evaluate(
            energy_result=energy_sim,
            assumptions=state["assumptions"],
            initial_soc_percent=state.get("initial_soc_percent", 80.0),
            required_connector=vehicle_profile.connector_type,
            no_compatible_connector=not stations,
            detour_distance_exceeded=detour_distance_exceeded,
            detour_time_exceeded=detour_time_exceeded,
        )
    return {
        "candidate_stations": stations,
        "no_compatible_connector": not stations,
        "detour_distance_exceeded": bool(detour_distance_exceeded and not ordered),
        "detour_time_exceeded": bool(detour_time_exceeded and not ordered),
        "energy_result": energy_sim,
        "route_result": selected_route,
        "feasibility_verdict": verdict,
        "environment": environment,
        "environment_degraded": environment.is_degraded,
        "route_energy_alternatives": ordered,
        "station_provider_unavailable": station_provider_unavailable,
        "station_route_validation_failed": station_route_validation_failed,
        "station_routing_rate_limited": station_routing_rate_limited,
        "routing_retry_after_seconds": routing_retry_after_seconds,
        "station_routing_budget_exhausted": station_routing_budget_exhausted,
    }


def feasibility_node(state: AgentState) -> dict:
    emit_planning_progress("Đang kiểm tra khả năng đi qua từng chặng và mức SOC dự phòng")
    if "energy_result" not in state or "assumptions" not in state:
        return {}

    verdict = get_planning_runtime().feasibility_tool.evaluate(
        energy_result=state["energy_result"],
        assumptions=state["assumptions"],
        initial_soc_percent=state.get("initial_soc_percent", 80.0),
        required_connector=state["vehicle_profile"].connector_type,
        no_compatible_connector=state.get("no_compatible_connector", False),
        detour_distance_exceeded=state.get("detour_distance_exceeded", False),
        detour_time_exceeded=state.get("detour_time_exceeded", False),
    )
    return {"feasibility_verdict": verdict}


def recovery_node(state: AgentState) -> dict:
    emit_planning_progress("Đang tìm phương án phục hồi khi tuyến hoặc SOC chưa đạt")
    """Use secondary discovery only after the official deterministic search failed."""
    if state.get("feasibility_verdict") is None or state["feasibility_verdict"].is_feasible:
        return {}
    runtime = get_planning_runtime()
    if not callable(getattr(runtime.station_service, "find_recovery_station_window", None)):
        return {"recovery_exhausted": True}

    route_result = state.get("route_result")
    vehicle_profile = state.get("vehicle_profile")
    environment = state.get("environment")
    if route_result is None or vehicle_profile is None or environment is None:
        return {"recovery_exhausted": True}

    recovered = AdaptiveStationPlanner(
        routing_provider=runtime.routing_provider,
        station_service=runtime.station_service,
        energy_tool=runtime.energy_tool,
        feasibility_tool=runtime.feasibility_tool,
        station_edge_repository=runtime.station_edge_repository,
        station_graph_enabled=runtime.station_graph_enabled,
        station_graph_routing_provider=runtime.station_graph_routing_provider,
        station_graph_routing_profile=runtime.station_graph_routing_profile,
        station_graph_road_version=runtime.station_graph_road_version,
        station_graph_edge_max_age_seconds=runtime.station_graph_edge_max_age_seconds,
    ).plan(
        base_route=route_result,
        origin_lat=state["origin_lat"],
        origin_lng=state["origin_lng"],
        destination_lat=state["destination_lat"],
        destination_lng=state["destination_lng"],
        origin_name=state.get("origin_name", "Origin"),
        destination_name=state.get("destination_name", "Destination"),
        initial_soc_percent=state.get("initial_soc_percent", 80.0),
        vehicle_profile=vehicle_profile,
        assumptions=state["assumptions"],
        environment=environment,
        search_profiles=tuple(
            AdaptiveSearchProfile(
                corridor_buffer_km=profile.corridor_buffer_km,
                detour_distance_per_stop_km=profile.detour_distance_per_stop_km,
                detour_duration_per_stop_min=profile.detour_duration_per_stop_min,
            )
            for profile in _STATION_SEARCH_PROFILES
        ),
        source="RECOVERY",
        require_charging_stop=True,
    )
    if recovered.routing_rate_limited:
        return {
            "recovery_exhausted": True,
            "station_routing_rate_limited": True,
            "routing_retry_after_seconds": recovered.retry_after_seconds,
        }
    if recovered.routing_budget_exhausted:
        return {
            "recovery_exhausted": True,
            "station_routing_budget_exhausted": True,
        }
    excluded_station_ids = set(state.get("excluded_station_ids", []))
    if not recovered.validated:
        merged = {station.station_id: station for station in state.get("candidate_stations", [])}
        for station in recovered.discovered_stations:
            if station.station_id in excluded_station_ids:
                continue
            merged.setdefault(station.station_id, station)
        return {
            "candidate_stations": list(merged.values()),
            "recovery_exhausted": True,
            "recovery_provider_unavailable": recovered.provider_unavailable,
        }

    ordered = sorted(
        [
            item for item in recovered.validated
            if not excluded_station_ids.intersection(
                stop.station_id for stop in item.energy.charging_stops
            )
        ],
        key=lambda item: (
            item.route.duration_min + item.energy.total_charge_time_min,
            -item.energy.min_soc_encountered,
        ),
    )[:3]
    if not ordered:
        return {
            "candidate_stations": [
                station for station in recovered.discovered_stations
                if station.station_id not in excluded_station_ids
            ],
            "recovery_exhausted": True,
            "recovery_provider_unavailable": recovered.provider_unavailable,
        }
    selected = ordered[0]
    return {
        "candidate_stations": recovered.discovered_stations,
        "energy_result": selected.energy,
        "route_result": selected.route,
        "feasibility_verdict": selected.verdict,
        "route_energy_alternatives": [
            {
                "route": item.route,
                "energy": item.energy,
                "verdict": item.verdict,
                "base_route": item.base_route,
                "includes_backtracking": item.includes_backtracking,
                "strategy": "BALANCED",
            }
            for item in ordered
        ],
        "recovery_mode": "OPENAI_STATION_SEARCH",
        "recovery_exhausted": False,
        "recovery_provider_unavailable": False,
    }


def no_feasible_plan_node(state: AgentState) -> dict:
    emit_planning_progress("Đã hoàn tất kiểm tra: chưa có phương án an toàn được xác minh")
    """Return a refusal outcome without inventing or persisting a plan."""
    verdict = state["feasibility_verdict"]
    reason_text = ", ".join(verdict.reason_codes) or "UNKNOWN_SAFETY_VIOLATION"
    summary = f"Không có phương án an toàn đã được chứng minh cho chuyến đi ({reason_text})."
    reserve_soc = state["assumptions"].reserve_soc_percent
    minimum_initial_soc: float | None = reserve_soc
    energy_result = state.get("energy_result")
    route_result = state.get("route_result")
    vehicle_profile = state.get("vehicle_profile")
    direct_route_distance_km: float | None = None
    estimated_reachable_distance_km: float | None = None
    estimated_energy_required_kwh: float | None = None
    available_energy_before_reserve_kwh: float | None = None
    energy_shortfall_kwh: float | None = None
    estimated_minimum_charging_stops: int | None = None
    usable_battery_kwh: float | None = None
    nearest_candidate_station_name: str | None = None
    nearest_candidate_station_distance_km: float | None = None
    candidates = state.get("candidate_stations", [])
    if candidates:
        nearest_candidate = min(
            candidates,
            key=lambda station: station.distance_from_origin_km,
        )
        nearest_candidate_station_name = nearest_candidate.name
        nearest_candidate_station_distance_km = max(
            0.0, nearest_candidate.distance_from_origin_km
        )
    if energy_result is not None and route_result is not None and vehicle_profile is not None:
        direct_route_distance_km = max(0.0, route_result.distance_km)
        usable_battery_kwh = max(10.0, vehicle_profile.usable_capacity_kwh)
        effective_consumption_kwh_per_km = (
            energy_result.effective_consumption_wh_per_km / 1000.0
        )
        estimated_energy_required_kwh = (
            direct_route_distance_km * effective_consumption_kwh_per_km
        )
        initial_soc = min(100.0, max(0.0, state.get("initial_soc_percent", 80.0)))
        available_energy_before_reserve_kwh = max(
            0.0,
            usable_battery_kwh * (initial_soc - reserve_soc) / 100.0,
        )
        if effective_consumption_kwh_per_km > 0:
            estimated_reachable_distance_km = (
                available_energy_before_reserve_kwh
                / effective_consumption_kwh_per_km
            )
        energy_shortfall_kwh = max(
            0.0,
            estimated_energy_required_kwh - available_energy_before_reserve_kwh,
        )
        energy_available_per_full_charge_kwh = max(
            0.0,
            usable_battery_kwh * (100.0 - reserve_soc) / 100.0,
        )
        if energy_available_per_full_charge_kwh > 0:
            estimated_minimum_charging_stops = math.ceil(
                energy_shortfall_kwh / energy_available_per_full_charge_kwh
            )
        direct_required = reserve_soc + (
            direct_route_distance_km
            * energy_result.effective_consumption_wh_per_km
            / 1000.0
            / usable_battery_kwh
            * 100.0
        )
        minimum_initial_soc = (
            max(reserve_soc, direct_required) if direct_required <= 100.0 else None
        )
    suggestions = []
    if minimum_initial_soc is not None:
        suggestions.append(
            f"Tăng SOC khởi hành lên ít nhất khoảng {minimum_initial_soc:.1f}% để đi thẳng theo mô hình hiện tại."
        )
    else:
        suggestions.append(
            "Không thể đi thẳng chỉ bằng một lần sạc đầy; cần một chuỗi trạm sạc đã được xác minh."
        )
    suggestions.extend(
        [
            "Chọn một điểm dừng sạc khác hoặc thay đổi điểm đến.",
            "Kiểm tra lại khi dữ liệu trạm hoặc tuyến đường được cập nhật.",
        ]
    )
    outcome = NoFeasiblePlan(
        trip_id=state.get("trip_id", "unknown-trip"),
        risk_assessment=verdict,
        assumptions=state["assumptions"],
        charging_stops=[],
        summary=summary,
        minimum_initial_soc_percent=(
            round(minimum_initial_soc, 1) if minimum_initial_soc is not None else None
        ),
        direct_route_distance_km=(
            round(direct_route_distance_km, 2)
            if direct_route_distance_km is not None
            else None
        ),
        estimated_reachable_distance_km=(
            round(estimated_reachable_distance_km, 2)
            if estimated_reachable_distance_km is not None
            else None
        ),
        estimated_energy_required_kwh=(
            round(estimated_energy_required_kwh, 2)
            if estimated_energy_required_kwh is not None
            else None
        ),
        available_energy_before_reserve_kwh=(
            round(available_energy_before_reserve_kwh, 2)
            if available_energy_before_reserve_kwh is not None
            else None
        ),
        energy_shortfall_kwh=(
            round(energy_shortfall_kwh, 2)
            if energy_shortfall_kwh is not None
            else None
        ),
        estimated_minimum_charging_stops=estimated_minimum_charging_stops,
        vehicle_profile_name=(vehicle_profile.name if vehicle_profile is not None else None),
        usable_battery_kwh=(
            round(usable_battery_kwh, 2) if usable_battery_kwh is not None else None
        ),
        nearest_candidate_station_name=nearest_candidate_station_name,
        nearest_candidate_station_distance_km=(
            round(nearest_candidate_station_distance_km, 2)
            if nearest_candidate_station_distance_km is not None
            else None
        ),
        evaluated_station_count=len(candidates),
        suggestions=suggestions,
        search_scope="ADAPTIVE_CORRIDOR_5_10_20_KM",
        created_at=datetime.now(UTC),
    )
    return {
        "no_feasible_plan": outcome,
        "summary": summary,
        "response": summary,
        "analysis": "Planning stopped by deterministic feasibility rules.",
    }


def proposal_node(state: AgentState) -> dict:
    emit_planning_progress("Đang xếp hạng và hoàn thiện phương án hành trình")
    if "route_result" not in state or "energy_result" not in state or "feasibility_verdict" not in state:
        return {
            "response": state.get("response", "AI EV Agent đã sẵn sàng."),
            "analysis": state.get("analysis", ""),
        }

    assumptions = state["assumptions"]
    environment = state.get("environment")
    raw_alternatives = state.get("route_energy_alternatives", [])
    if not raw_alternatives:
        raw_alternatives = [
            {
                "route": state["route_result"],
                "energy": state["energy_result"],
                "verdict": state["feasibility_verdict"],
                "base_route": state["route_result"],
                "includes_backtracking": False,
                "strategy": "BALANCED",
            }
        ]

    proposals: list[PlanProposal] = []
    for rank, item in enumerate(raw_alternatives[:3], start=1):
        route_res = item["route"]
        base_route = item.get("base_route", route_res)
        energy_res = item["energy"]
        verdict = item["verdict"]
        if environment and environment.is_degraded:
            warning = environment.warning or "Live environment data is unavailable."
            verdict = verdict.model_copy(
                update={
                    "level": (
                        "MEDIUM_RISK" if verdict.level == "LOW_RISK" else verdict.level
                    ),
                    "reasons": [*verdict.reasons, warning],
                    "reason_codes": [
                        *verdict.reason_codes,
                        "ENVIRONMENT_DATA_FALLBACK",
                    ],
                    "risk_score": max(verdict.risk_score, 35.0),
                }
            )
        detour_distance = max(0.0, route_res.distance_km - base_route.distance_km)
        detour_duration = max(0.0, route_res.duration_min - base_route.duration_min)
        includes_backtracking = bool(item.get("includes_backtracking", False))
        route_geo = RouteGeometry(
            polyline=route_res.polyline,
            distance_km=route_res.distance_km,
            duration_min=route_res.duration_min,
            segments=[
                RouteSegment(
                    from_name=segment.from_name,
                    to_name=segment.to_name,
                    distance_km=segment.distance_km,
                    duration_min=segment.duration_min,
                    start_lat=segment.start_lat,
                    start_lng=segment.start_lng,
                    end_lat=segment.end_lat,
                    end_lng=segment.end_lng,
                )
                for segment in route_res.segments
            ],
            provider=route_res.provider,
            source_url=route_res.source_url,
            retrieved_at=route_res.retrieved_at,
            direct_distance_km=base_route.distance_km,
            detour_distance_km=round(detour_distance, 2),
            detour_duration_min=round(detour_duration, 1),
            includes_backtracking=includes_backtracking,
        )

        stop_count = len(energy_res.charging_stops)
        if stop_count == 0:
            summary = (
                f"Lộ trình trực tiếp {route_res.distance_km:.1f} km; SOC tại đích "
                f"{energy_res.final_arrival_soc_percent:.1f}%. Không cần sạc giữa chặng."
            )
        else:
            names = " → ".join(stop.name for stop in energy_res.charging_stops)
            backtrack_text = " Có đoạn quay lại trạm gần điểm xuất phát." if includes_backtracking else ""
            summary = (
                f"Lộ trình {route_res.distance_km:.1f} km, {stop_count} điểm sạc ({names}), "
                f"sạc khoảng {energy_res.total_charge_time_min:.0f} phút; "
                f"SOC tại đích {energy_res.final_arrival_soc_percent:.1f}%.{backtrack_text}"
            )
        strategy = item.get("strategy", "BALANCED")
        selection_reason = {
            "BALANCED": "Cân bằng thời gian hành trình, thời gian sạc, đường vòng và biên SOC.",
            "FASTEST": "Có tổng thời gian lái và sạc thấp nhất trong các phương án đã xác minh.",
            "SAFEST": "Có biên SOC thấp nhất trên hành trình cao hơn các phương án còn lại.",
        }[strategy]
        proposals.append(
            PlanProposal(
                plan_id=f"plan-{uuid4().hex[:12]}",
                trip_id=state.get("trip_id", "unknown-trip"),
                version=1,
                status="PENDING",
                route=route_geo,
                charging_stops=energy_res.charging_stops,
                risk_assessment=verdict,
                assumptions=assumptions,
                soc_points=energy_res.soc_points,
                final_arrival_soc_percent=energy_res.final_arrival_soc_percent,
                effective_consumption_wh_per_km=energy_res.effective_consumption_wh_per_km,
                environment=environment,
                provenance=[
                    source
                    for source in [
                        DataProvenance(
                            source=(
                                "GOONG_DIRECTIONS"
                                if route_res.provider == "GOONG_DIRECTIONS"
                                else "TEST_FIXTURE"
                            ),
                            source_url=route_res.source_url,
                            retrieved_at=route_res.retrieved_at or datetime.now(UTC),
                        ),
                        environment.weather_provenance if environment else None,
                        environment.elevation_provenance if environment else None,
                        *[stop.provenance for stop in energy_res.charging_stops],
                    ]
                    if source is not None
                ],
                summary=summary,
                alternative_rank=rank,
                strategy=strategy,
                selection_reason=selection_reason,
                created_at=datetime.now(UTC),
            )
        )

    proposals = get_planning_runtime().plan_ranker.rank(proposals)
    proposal = proposals[0]
    return {
        "plan_proposal": proposal,
        "plan_alternatives": proposals,
        "summary": proposal.summary,
        "response": proposal.summary,
        "analysis": (
            f"status={proposal.status}, risk={proposal.risk_assessment.level}, "
            f"alternatives={len(proposals)}, charging_stops={len(proposal.charging_stops)}."
        ),
    }
