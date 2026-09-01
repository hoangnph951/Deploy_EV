from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace

from src.packages.core.planning.application.ports import DeterministicPlanRanker, SafePlanRanker
from src.packages.core.trips.application.station_edge_repository import StationEdgeRepository
from src.packages.core.trips.infrastructure.energy_tool import EnergyTool
from src.packages.core.trips.infrastructure.environment import (
    EnvironmentProvider,
    OpenMeteoEnvironmentProvider,
)
from src.packages.core.trips.infrastructure.feasibility_tool import FeasibilityTool
from src.packages.core.trips.infrastructure.routing import GoongRoutingProvider, RoutingProvider
from src.packages.core.trips.infrastructure.station_service import StationDataService, StationService


@dataclass(frozen=True)
class PlanningRuntime:
    """Dependencies required by the deterministic planning workflow.

    The runtime is immutable and owned by one orchestrator instance. This keeps
    request execution independent from module-level mutable provider state.
    """

    routing_provider: RoutingProvider
    station_service: StationService
    environment_provider: EnvironmentProvider
    energy_tool: EnergyTool
    feasibility_tool: FeasibilityTool
    plan_ranker: SafePlanRanker
    station_edge_repository: StationEdgeRepository | None = None
    station_graph_enabled: bool = False
    station_graph_routing_provider: str = "GOONG_DIRECTIONS"
    station_graph_routing_profile: str = "car"
    station_graph_road_version: str = "goong-car-v1"
    station_graph_edge_max_age_seconds: float = 86400.0

    def with_routing_provider(self, provider: RoutingProvider) -> PlanningRuntime:
        return replace(self, routing_provider=provider)


def default_planning_runtime() -> PlanningRuntime:
    return PlanningRuntime(
        routing_provider=GoongRoutingProvider(api_key=""),
        station_service=StationDataService(),
        environment_provider=OpenMeteoEnvironmentProvider(),
        energy_tool=EnergyTool(),
        feasibility_tool=FeasibilityTool(),
        plan_ranker=DeterministicPlanRanker(),
    )


_runtime_var: ContextVar[PlanningRuntime | None] = ContextVar("planning_runtime", default=None)
_progress_callback: ContextVar[Callable[[str], None] | None] = ContextVar("planning_progress_callback", default=None)

def emit_planning_progress(message: str) -> None:
    callback = _progress_callback.get()
    if callback is not None:
        callback(message)

@contextmanager
def use_planning_progress(callback: Callable[[str], None] | None) -> Iterator[None]:
    token = _progress_callback.set(callback)
    try:
        yield
    finally:
        _progress_callback.reset(token)


def get_planning_runtime() -> PlanningRuntime:
    runtime = _runtime_var.get()
    if runtime is None:
        # Compatibility default for direct node imports and existing tests.
        return _legacy_runtime
    return runtime


@contextmanager
def use_planning_runtime(runtime: PlanningRuntime) -> Iterator[None]:
    token = _runtime_var.set(runtime)
    try:
        yield
    finally:
        _runtime_var.reset(token)


_legacy_runtime = default_planning_runtime()


def set_legacy_runtime(runtime: PlanningRuntime) -> None:
    global _legacy_runtime
    _legacy_runtime = runtime


def get_legacy_runtime() -> PlanningRuntime:
    return _legacy_runtime
