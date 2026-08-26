from __future__ import annotations

from typing import Any, TypedDict

from src.packages.contracts.trips import (
    AssumptionSnapshot,
    EnvironmentSnapshot,
    NoFeasiblePlan,
    PlanProposal,
    RiskAssessment,
)
from src.packages.core.trips.domain.entities import VehicleProfile
from src.packages.core.trips.infrastructure.energy_tool import EnergySimulationResult
from src.packages.core.trips.infrastructure.routing import RoutingResult
from src.packages.core.trips.infrastructure.station_service import CandidateStation


class AgentState(TypedDict, total=False):
    """Shared state schema for the EV Trip Planning LangGraph flow."""

    trip_id: str
    owner_id: str
    origin_name: str
    origin_lat: float
    origin_lng: float
    destination_name: str
    destination_lat: float
    destination_lng: float
    initial_soc_percent: float
    excluded_station_ids: list[str]
    vehicle_profile: VehicleProfile
    assumptions: AssumptionSnapshot
    route_result: RoutingResult
    candidate_stations: list[CandidateStation]
    seed_candidate_stations: list[CandidateStation]
    no_compatible_connector: bool
    detour_distance_exceeded: bool
    detour_time_exceeded: bool
    energy_result: EnergySimulationResult
    environment: EnvironmentSnapshot
    environment_degraded: bool
    feasibility_verdict: RiskAssessment
    plan_proposal: PlanProposal
    plan_alternatives: list[PlanProposal]
    route_energy_alternatives: list[dict[str, Any]]
    no_feasible_plan: NoFeasiblePlan
    recovery_mode: str
    recovery_exhausted: bool
    station_provider_unavailable: bool
    recovery_provider_unavailable: bool
    station_route_validation_failed: bool
    station_routing_rate_limited: bool
    routing_retry_after_seconds: float | None
    station_routing_budget_exhausted: bool
    routing_search_budget_reason: str | None
    official_search_exhausted: bool
    recovery_search_exhausted: bool
    proven_infeasible: bool
    routing_error: str
    summary: str
    error: str | None
    metadata: dict[str, Any]
    response: str
    analysis: str
