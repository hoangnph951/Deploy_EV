from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from src.packages.contracts.trips import AssumptionSnapshot
from src.packages.core.planning.domain.outcomes import PlanningOutcomeKind
from src.packages.core.trips.domain.entities import VehicleProfile


@dataclass(frozen=True)
class PlanningRequest:
    trip_id: str
    owner_id: str
    origin_name: str
    origin_lat: float
    origin_lng: float
    destination_name: str
    destination_lat: float
    destination_lng: float
    initial_soc_percent: float
    vehicle_profile: VehicleProfile
    assumptions: AssumptionSnapshot
    excluded_station_ids: list[str] | None = None

    def to_state(self) -> dict[str, Any]:
        return {
            "trip_id": self.trip_id,
            "owner_id": self.owner_id,
            "origin_name": self.origin_name,
            "origin_lat": self.origin_lat,
            "origin_lng": self.origin_lng,
            "destination_name": self.destination_name,
            "destination_lat": self.destination_lat,
            "destination_lng": self.destination_lng,
            "initial_soc_percent": self.initial_soc_percent,
            "vehicle_profile": self.vehicle_profile,
            "assumptions": self.assumptions,
            "excluded_station_ids": list(self.excluded_station_ids or []),
        }


@dataclass(frozen=True)
class PlanningExecution:
    state: dict[str, Any]

    @property
    def outcome(self) -> PlanningOutcomeKind:
        if "plan_proposal" in self.state:
            return PlanningOutcomeKind.SUCCEEDED
        if any(
            self.state.get(key)
            for key in (
                "station_provider_unavailable",
                "station_route_validation_failed",
                "station_routing_rate_limited",
                "station_routing_budget_exhausted",
            )
        ):
            return PlanningOutcomeKind.REQUIRES_USER_ACTION
        return PlanningOutcomeKind.INFEASIBLE


class PlanningOrchestrator(Protocol):
    def plan(self, request: PlanningRequest) -> PlanningExecution: ...
