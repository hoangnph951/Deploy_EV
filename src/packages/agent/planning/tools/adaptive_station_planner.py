from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Literal

from src.packages.contracts.trips import AssumptionSnapshot, EnvironmentSnapshot, RiskAssessment
from src.packages.core.trips.application.station_edge_repository import StationEdgeRepository
from src.packages.core.trips.domain.entities import VehicleProfile
from src.packages.core.trips.infrastructure.energy_tool import EnergySimulationResult, EnergyTool
from src.packages.core.trips.infrastructure.feasibility_tool import FeasibilityTool
from src.packages.core.trips.infrastructure.observability import metrics
from src.packages.core.trips.infrastructure.routing import (
    RouteSegmentData,
    RoutingProvider,
    RoutingResult,
    RoutingUnavailableError,
)
from src.packages.core.trips.infrastructure.station_graph_repository import edge_from_route, route_from_edge
from src.packages.core.trips.infrastructure.station_service import (
    CandidateStation,
    StationProviderError,
    StationService,
)


@dataclass(frozen=True)
class AdaptiveSearchProfile:
    corridor_buffer_km: float
    detour_distance_per_stop_km: float
    detour_duration_per_stop_min: float


@dataclass(frozen=True)
class AdaptivePlanCandidate:
    route: RoutingResult
    energy: EnergySimulationResult
    verdict: RiskAssessment
    base_route: RoutingResult
    includes_backtracking: bool


@dataclass(frozen=True)
class AdaptivePlanningResult:
    validated: list[AdaptivePlanCandidate]
    discovered_stations: list[CandidateStation]
    attempted_edge_count: int
    route_failure_count: int
    search_source: Literal["OFFICIAL", "RECOVERY"]
    provider_unavailable: bool = False
    routing_rate_limited: bool = False
    retry_after_seconds: float | None = None
    routing_budget_exhausted: bool = False


@dataclass(frozen=True)
class _SearchState:
    progress_km: float
    lat: float
    lng: float
    stations: tuple[CandidateStation, ...]
    legs: tuple[RoutingResult, ...]


class AdaptiveStationPlanner:
    """Build a verified charging chain without a global station shortlist."""

    _DETAIL_BACKFILL_BUDGETS = (24, 48, 96)
    _TARGET_CANDIDATES = 12
    _BRANCH_WIDTH = 3
    _STATE_WIDTH = 6
    _EDGE_VALIDATION_LIMIT = 9
    _MAX_EDGE_VALIDATIONS = 120

    def __init__(
        self,
        *,
        routing_provider: RoutingProvider,
        station_service: StationService,
        energy_tool: EnergyTool,
        feasibility_tool: FeasibilityTool,
        station_edge_repository: StationEdgeRepository | None = None,
        station_graph_enabled: bool = False,
        station_graph_routing_provider: str = "GOONG_DIRECTIONS",
        station_graph_routing_profile: str = "car",
        station_graph_road_version: str = "goong-car-v1",
        station_graph_edge_max_age_seconds: float = 86400.0,
    ):
        self._routing_provider = routing_provider
        self._station_service = station_service
        self._energy_tool = energy_tool
        self._feasibility_tool = feasibility_tool
        self._station_edge_repository = station_edge_repository
        self._station_graph_enabled = station_graph_enabled
        self._station_graph_routing_provider = station_graph_routing_provider
        self._station_graph_routing_profile = station_graph_routing_profile
        self._station_graph_road_version = station_graph_road_version
        self._station_graph_edge_max_age_seconds = station_graph_edge_max_age_seconds

    def plan(
        self,
        *,
        base_route: RoutingResult,
        origin_lat: float,
        origin_lng: float,
        destination_lat: float,
        destination_lng: float,
        origin_name: str,
        destination_name: str,
        initial_soc_percent: float,
        vehicle_profile: VehicleProfile,
        assumptions: AssumptionSnapshot,
        environment: EnvironmentSnapshot,
        search_profiles: tuple[AdaptiveSearchProfile, ...],
        source: Literal["OFFICIAL", "RECOVERY"] = "OFFICIAL",
        max_results: int = 8,
        require_charging_stop: bool = False,
    ) -> AdaptivePlanningResult:
        effective_wh_km = self._energy_tool.effective_consumption_rate(
            base_route.distance_km,
            vehicle_profile,
            assumptions,
            environment,
        )
        full_range_km = _safe_range_km(
            100.0,
            assumptions.reserve_soc_percent,
            vehicle_profile.usable_capacity_kwh,
            effective_wh_km,
        )
        initial_range_km = _safe_range_km(
            initial_soc_percent,
            assumptions.reserve_soc_percent,
            vehicle_profile.usable_capacity_kwh,
            effective_wh_km,
        )
        minimum_stops = math.ceil(
            max(0.0, base_route.distance_km - initial_range_km) / max(1.0, full_range_km)
        )
        max_stops = max(1, minimum_stops + 3)
        # When charging is explicitly requested, the chain must contain the
        # number of stops required by the vehicle's safe range.  Without this
        # lower bound the search can accept an early one-stop destination leg
        # and never return the complete multi-stop itinerary for long trips.
        minimum_charging_stops = max(1, minimum_stops) if require_charging_stop else 0

        discovered: dict[str, CandidateStation] = {}
        validated: list[AdaptivePlanCandidate] = []
        attempted_edges = 0
        route_failures = 0
        provider_unavailable = False
        routing_rate_limited = False
        retry_after_seconds: float | None = None
        routing_budget_exhausted = False
        for profile in search_profiles:
            try:
                result = self._search_profile(
                    base_route=base_route,
                    origin_lat=origin_lat,
                    origin_lng=origin_lng,
                    destination_lat=destination_lat,
                    destination_lng=destination_lng,
                    origin_name=origin_name,
                    destination_name=destination_name,
                    initial_soc_percent=initial_soc_percent,
                    vehicle_profile=vehicle_profile,
                    assumptions=assumptions,
                    environment=environment,
                    profile=profile,
                    source=source,
                    max_stops=max_stops,
                    max_results=max_results,
                    effective_wh_km=effective_wh_km,
                    full_range_km=full_range_km,
                    require_charging_stop=require_charging_stop,
                    minimum_charging_stops=minimum_charging_stops,
                )
            except StationProviderError:
                provider_unavailable = True
                # A narrow profile can fail while a wider corridor still has
                # grounded candidates. Do not turn one failed provider window
                # into a terminal failure for the complete route.
                continue
            for station in result.discovered_stations:
                discovered.setdefault(station.station_id, station)
            validated.extend(result.validated)
            attempted_edges += result.attempted_edge_count
            route_failures += result.route_failure_count
            provider_unavailable = (
                provider_unavailable or result.provider_unavailable
            )
            if result.routing_rate_limited:
                routing_rate_limited = True
                retry_after_seconds = result.retry_after_seconds
                break
            if result.routing_budget_exhausted:
                routing_budget_exhausted = True
                break
            if validated and not require_charging_stop:
                break

        deduplicated = _deduplicate_plans(validated)
        if require_charging_stop:
            deduplicated.sort(
                key=lambda item: (
                    -len(item.energy.charging_stops),
                    item.route.duration_min + item.energy.total_charge_time_min,
                )
            )
        return AdaptivePlanningResult(
            validated=deduplicated[:max_results],
            discovered_stations=sorted(
                discovered.values(), key=lambda station: station.distance_from_origin_km
            ),
            attempted_edge_count=attempted_edges,
            route_failure_count=route_failures,
            search_source=source,
            provider_unavailable=bool(provider_unavailable and not deduplicated),
            routing_rate_limited=routing_rate_limited,
            retry_after_seconds=retry_after_seconds,
            routing_budget_exhausted=routing_budget_exhausted,
        )

    def _search_profile(
        self,
        *,
        base_route: RoutingResult,
        origin_lat: float,
        origin_lng: float,
        destination_lat: float,
        destination_lng: float,
        origin_name: str,
        destination_name: str,
        initial_soc_percent: float,
        vehicle_profile: VehicleProfile,
        assumptions: AssumptionSnapshot,
        environment: EnvironmentSnapshot,
        profile: AdaptiveSearchProfile,
        source: Literal["OFFICIAL", "RECOVERY"],
        max_stops: int,
        max_results: int,
        effective_wh_km: float,
        full_range_km: float,
        require_charging_stop: bool,
        minimum_charging_stops: int,
    ) -> AdaptivePlanningResult:
        states = [
            _SearchState(
                progress_km=0.0,
                lat=origin_lat,
                lng=origin_lng,
                stations=(),
                legs=(),
            )
        ]
        completed: list[AdaptivePlanCandidate] = []
        discovered: dict[str, CandidateStation] = {}
        attempted_edges = 0
        route_failures = 0
        provider_unavailable = False
        seen_paths: set[tuple[str, ...]] = set()

        for _depth in range(max_stops + 1):
            next_states: list[_SearchState] = []
            for state in states:
                destination_leg = None
                remaining_progress = max(0.0, base_route.distance_km - state.progress_km)
                departure_soc = initial_soc_percent if not state.stations else 100.0
                safe_range = _safe_range_km(
                    departure_soc,
                    assumptions.reserve_soc_percent,
                    vehicle_profile.usable_capacity_kwh,
                    effective_wh_km,
                )
                if remaining_progress <= safe_range * 1.15:
                    if attempted_edges >= self._MAX_EDGE_VALIDATIONS:
                        return _budget_exhausted_result(
                            completed, discovered, attempted_edges, route_failures, source
                        )
                    attempted_edges += 1
                    try:
                        destination_leg = (
                            base_route
                            if not state.stations
                            else self._routing_provider.get_route(
                                state.lat,
                                state.lng,
                                destination_lat,
                                destination_lng,
                            )
                        )
                    except RoutingUnavailableError as exc:
                        route_failures += 1
                        if exc.http_status == 429:
                            return AdaptivePlanningResult(
                                validated=completed,
                                discovered_stations=list(discovered.values()),
                                attempted_edge_count=attempted_edges,
                                route_failure_count=route_failures,
                                search_source=source,
                                routing_rate_limited=True,
                                retry_after_seconds=exc.retry_after_seconds,
                            )

                if destination_leg is not None:
                    candidate = self._validate_complete_state(
                        state=state,
                        destination_leg=destination_leg,
                        base_route=base_route,
                        initial_soc_percent=initial_soc_percent,
                        vehicle_profile=vehicle_profile,
                        assumptions=assumptions,
                        environment=environment,
                        profile=profile,
                        require_charging_stop=require_charging_stop,
                        minimum_charging_stops=minimum_charging_stops,
                    )
                    if candidate is not None:
                        completed.append(candidate)
                        if len(completed) >= max_results:
                            break

                if len(state.stations) >= max_stops:
                    continue

                try:
                    candidates = self._discover_with_backfill(
                        state=state,
                        base_route=base_route,
                        origin_lat=origin_lat,
                        origin_lng=origin_lng,
                        destination_lat=destination_lat,
                        destination_lng=destination_lng,
                        origin_name=origin_name,
                        destination_name=destination_name,
                        compatible_connectors=(vehicle_profile.connector_type.upper(),),
                        profile=profile,
                        source=source,
                        safe_range_km=safe_range,
                        assumptions=assumptions,
                    )
                except StationProviderError:
                    # Discovery is state-local. Other states in the frontier
                    # may use a different reachable window and must still be
                    # allowed to complete the charging chain.
                    provider_unavailable = True
                    continue
                for station in candidates:
                    discovered.setdefault(station.station_id, station)

                reachable: list[tuple[CandidateStation, RoutingResult]] = []
                estimated_reachable = [
                    station
                    for station in candidates
                    if (
                        max(0.0, station.distance_from_origin_km - state.progress_km)
                        + max(0.0, station.detour_distance_km)
                    )
                    <= safe_range * 1.05
                ]
                validation_count = 0
                selected_station_ids = {
                    item.station_id for item in state.stations
                }
                for batch in _middle_then_closer_batches(estimated_reachable):
                    for station in batch:
                        if validation_count >= self._EDGE_VALIDATION_LIMIT:
                            break
                        if station.station_id in selected_station_ids:
                            continue
                        if (
                            state.stations
                            and station.distance_from_origin_km
                            <= state.progress_km + 0.05
                        ):
                            continue
                        if attempted_edges >= self._MAX_EDGE_VALIDATIONS:
                            return _budget_exhausted_result(
                                completed,
                                discovered,
                                attempted_edges,
                                route_failures,
                                source,
                            )
                        validation_count += 1
                        attempted_edges += 1
                        try:
                            leg = self._route_station_edge(state, station)
                        except RoutingUnavailableError as exc:
                            route_failures += 1
                            if exc.http_status == 429:
                                return AdaptivePlanningResult(
                                    validated=completed,
                                    discovered_stations=list(discovered.values()),
                                    attempted_edge_count=attempted_edges,
                                    route_failure_count=route_failures,
                                    search_source=source,
                                    routing_rate_limited=True,
                                    retry_after_seconds=exc.retry_after_seconds,
                                )
                            continue
                        arrival_soc = departure_soc - _soc_cost_percent(
                            leg.distance_km,
                            vehicle_profile.usable_capacity_kwh,
                            effective_wh_km,
                        )
                        if arrival_soc + 1e-6 < assumptions.reserve_soc_percent:
                            continue
                        reachable.append((station, leg))

                    # Prefer three stations around the middle of the reachable
                    # window. Only retreat to the next, closer batch when none
                    # of the current batch passes exact routing and SOC checks.
                    if reachable or validation_count >= self._EDGE_VALIDATION_LIMIT:
                        break

                reachable.sort(
                    key=lambda item: (
                        item[0].station_status != "ACTIVE",
                        -item[0].distance_from_origin_km,
                        item[1].distance_km,
                        item[0].detour_distance_km,
                    )
                )
                for station, leg in reachable[: self._BRANCH_WIDTH]:
                    path = (*state.stations, station)
                    identity = tuple(item.station_id for item in path)
                    if identity in seen_paths:
                        continue
                    seen_paths.add(identity)
                    next_states.append(
                        _SearchState(
                            progress_km=max(state.progress_km, station.distance_from_origin_km),
                            lat=station.lat,
                            lng=station.lon,
                            stations=path,
                            legs=(*state.legs, leg),
                        )
                    )

            if not next_states:
                break
            next_states.sort(
                key=lambda state: (
                    -state.progress_km,
                    sum(leg.distance_km for leg in state.legs),
                    len(state.stations),
                )
            )
            states = next_states[: self._STATE_WIDTH]

        return AdaptivePlanningResult(
            validated=completed,
            discovered_stations=list(discovered.values()),
            attempted_edge_count=attempted_edges,
            route_failure_count=route_failures,
            search_source=source,
            # A transient failure in one narrow window is not an outage when
            # another profile produced a complete validated itinerary.
            provider_unavailable=bool(provider_unavailable and not completed),
            routing_rate_limited=False,
            retry_after_seconds=None,
            routing_budget_exhausted=False,
        )

    def _discover_with_backfill(
        self,
        *,
        state: _SearchState,
        base_route: RoutingResult,
        origin_lat: float,
        origin_lng: float,
        destination_lat: float,
        destination_lng: float,
        origin_name: str,
        destination_name: str,
        compatible_connectors: tuple[str, ...],
        profile: AdaptiveSearchProfile,
        require_charging_stop: bool = False,
        minimum_charging_stops: int = 0,
        source: Literal["OFFICIAL", "RECOVERY"],
        safe_range_km: float,
        assumptions: AssumptionSnapshot,
    ) -> list[CandidateStation]:
        finder_name = (
            "find_official_station_window" if source == "OFFICIAL" else "find_recovery_station_window"
        )
        finder = getattr(self._station_service, finder_name, None)
        if not callable(finder):
            finder = getattr(self._station_service, "find_station_window")

        merged: dict[str, CandidateStation] = {}
        detail_budgets = self._DETAIL_BACKFILL_BUDGETS if source == "OFFICIAL" else (96,)
        for detail_budget in detail_budgets:
            found = finder(
                polyline=base_route.polyline,
                origin_lat=origin_lat,
                origin_lng=origin_lng,
                dest_lat=destination_lat,
                dest_lng=destination_lng,
                progress_start_km=max(0.0, state.progress_km + (0.05 if state.stations else 0.0)),
                progress_end_km=min(
                    base_route.distance_km,
                    state.progress_km + safe_range_km,
                ),
                compatible_connectors=compatible_connectors,
                max_corridor_buffer_km=profile.corridor_buffer_km,
                max_detour_min=profile.detour_duration_per_stop_min,
                total_route_distance_km=base_route.distance_km,
                max_detail_candidates=detail_budget,
                target_candidate_count=self._TARGET_CANDIDATES,
                origin_radius_km=safe_range_km if not state.stations else None,
                origin_name=origin_name,
                dest_name=destination_name,
                stale_station_hours_threshold=assumptions.stale_station_hours_threshold,
            )
            for station in found:
                merged.setdefault(station.station_id, station)
            if len(merged) >= self._TARGET_CANDIDATES:
                break
        return list(merged.values())

    def _route_station_edge(
        self,
        state: _SearchState,
        station: CandidateStation,
    ) -> RoutingResult:
        repository = self._station_edge_repository
        from_id = state.stations[-1].catalog_location_id if state.stations else None
        to_id = station.catalog_location_id
        graph_eligible = (
            self._station_graph_enabled
            and repository is not None
            and from_id is not None
            and to_id is not None
        )
        if graph_eligible:
            edge = repository.get_edge(
                from_id,
                to_id,
                self._station_graph_routing_provider,
                self._station_graph_road_version,
            )
            if edge is not None and edge.routing_profile == self._station_graph_routing_profile:
                metrics.increment(
                    "station_graph_hits_total",
                    provider=self._station_graph_routing_provider,
                    road_version=self._station_graph_road_version,
                )
                return route_from_edge(
                    edge,
                    start_lat=state.lat,
                    start_lng=state.lng,
                    end_lat=station.lat,
                    end_lng=station.lon,
                )
            metrics.increment(
                "station_graph_misses_total",
                provider=self._station_graph_routing_provider,
                road_version=self._station_graph_road_version,
            )

        route = self._routing_provider.get_route(
            state.lat,
            state.lng,
            station.lat,
            station.lon,
        )
        if graph_eligible and route.provider == self._station_graph_routing_provider:
            repository.upsert_edge(
                edge_from_route(
                    from_location_id=from_id,
                    to_location_id=to_id,
                    routing_provider=self._station_graph_routing_provider,
                    routing_profile=self._station_graph_routing_profile,
                    road_version=self._station_graph_road_version,
                    route=route,
                    max_age_seconds=self._station_graph_edge_max_age_seconds,
                )
            )
        return route

    def _validate_complete_state(
        self,
        *,
        state: _SearchState,
        destination_leg: RoutingResult,
        base_route: RoutingResult,
        initial_soc_percent: float,
        vehicle_profile: VehicleProfile,
        assumptions: AssumptionSnapshot,
        environment: EnvironmentSnapshot,
        profile: AdaptiveSearchProfile,
        require_charging_stop: bool = False,
        minimum_charging_stops: int = 0,
    ) -> AdaptivePlanCandidate | None:
        legs = (*state.legs, destination_leg)
        route = _compose_route(legs)
        stop_count = len(state.stations)
        if require_charging_stop and stop_count < max(1, minimum_charging_stops):
            return None
        if stop_count:
            detour_distance = max(0.0, route.distance_km - base_route.distance_km)
            detour_duration = max(0.0, route.duration_min - base_route.duration_min)
            if detour_distance > profile.detour_distance_per_stop_km * stop_count:
                return None
            if detour_duration > profile.detour_duration_per_stop_min * stop_count:
                return None

        cumulative = 0.0
        exact_stations: list[CandidateStation] = []
        for index, station in enumerate(state.stations):
            cumulative += legs[index].distance_km
            exact_stations.append(replace(station, distance_from_origin_km=round(cumulative, 2)))
        energy = self._energy_tool.simulate_fixed_itinerary(
            leg_distances_km=[leg.distance_km for leg in legs],
            initial_soc_percent=initial_soc_percent,
            vehicle_profile=vehicle_profile,
            assumptions=assumptions,
            stations=exact_stations,
            environment=environment,
        )
        verdict = self._feasibility_tool.evaluate(
            energy_result=energy,
            assumptions=assumptions,
            initial_soc_percent=initial_soc_percent,
            required_connector=vehicle_profile.connector_type,
            no_compatible_connector=False,
        )
        if not verdict.is_feasible:
            return None
        return AdaptivePlanCandidate(
            route=route,
            energy=energy,
            verdict=verdict,
            base_route=base_route,
            includes_backtracking=bool(
                state.stations and state.stations[0].distance_from_origin_km <= 0.25
            ),
        )


def _safe_range_km(
    soc_percent: float,
    reserve_soc_percent: float,
    usable_capacity_kwh: float,
    effective_wh_km: float,
) -> float:
    available_kwh = max(0.0, soc_percent - reserve_soc_percent) / 100.0 * max(
        10.0, usable_capacity_kwh
    )
    return available_kwh * 1000.0 / max(1.0, effective_wh_km)


def _middle_then_closer_batches(
    candidates: list[CandidateStation],
) -> list[list[CandidateStation]]:
    """Try a middle group of three, then retreat in groups of three."""
    if not candidates:
        return []
    ordered = sorted(
        candidates,
        key=lambda station: (
            station.distance_from_origin_km,
            station.station_status != "ACTIVE",
            station.detour_distance_km,
            -station.max_power_kw,
        ),
    )
    middle_index = (len(ordered) - 1) // 2
    middle_start = max(0, middle_index - 1)
    middle_end = min(len(ordered), middle_start + 3)
    middle_start = max(0, middle_end - 3)
    middle = ordered[middle_start:middle_end]
    middle_target = sum(
        station.distance_from_origin_km for station in middle
    ) / len(middle)
    middle.sort(
        key=lambda station: (
            abs(station.distance_from_origin_km - middle_target),
            station.station_status != "ACTIVE",
            station.detour_distance_km,
            -station.max_power_kw,
        )
    )

    closer = list(reversed(ordered[:middle_start]))
    return [middle, *[closer[index : index + 3] for index in range(0, len(closer), 3)]]


def _soc_cost_percent(
    distance_km: float,
    usable_capacity_kwh: float,
    effective_wh_km: float,
) -> float:
    return (
        distance_km
        * effective_wh_km
        / 1000.0
        / max(10.0, usable_capacity_kwh)
        * 100.0
    )


def _compose_route(legs: tuple[RoutingResult, ...]) -> RoutingResult:
    polyline: list[list[float]] = []
    segments: list[RouteSegmentData] = []
    distance_km = 0.0
    duration_min = 0.0
    for leg in legs:
        if not polyline:
            polyline.extend(leg.polyline)
        elif leg.polyline:
            polyline.extend(leg.polyline[1:])
        distance_km += leg.distance_km
        duration_min += leg.duration_min
        segments.extend(leg.segments)
    first = legs[0]
    return RoutingResult(
        polyline=polyline,
        distance_km=round(distance_km, 2),
        duration_min=round(duration_min, 1),
        segments=segments,
        provider=first.provider,
        source_url=first.source_url,
        retrieved_at=first.retrieved_at,
    )


def _deduplicate_plans(plans: list[AdaptivePlanCandidate]) -> list[AdaptivePlanCandidate]:
    unique: dict[tuple[str, ...], AdaptivePlanCandidate] = {}
    for plan in plans:
        identity = tuple(stop.station_id for stop in plan.energy.charging_stops)
        unique.setdefault(identity, plan)
    return list(unique.values())


def _budget_exhausted_result(
    completed: list[AdaptivePlanCandidate],
    discovered: dict[str, CandidateStation],
    attempted_edges: int,
    route_failures: int,
    source: Literal["OFFICIAL", "RECOVERY"],
) -> AdaptivePlanningResult:
    return AdaptivePlanningResult(
        validated=completed,
        discovered_stations=list(discovered.values()),
        attempted_edge_count=attempted_edges,
        route_failure_count=route_failures,
        search_source=source,
        routing_budget_exhausted=True,
    )
