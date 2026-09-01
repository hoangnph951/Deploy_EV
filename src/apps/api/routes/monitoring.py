from fastapi import APIRouter, Depends

from src.apps.api.bootstrap.config import Settings, get_settings
from src.packages.contracts.monitoring import (
    SimulationDecisionRequest,
    SimulationState,
    SimulatorStartRequest,
)
from src.packages.core.auth.api.dependencies import get_current_user_id
from src.packages.core.monitoring.api.dependencies import get_monitoring_simulator_service
from src.packages.core.monitoring.application.service import MonitoringSimulatorService
from src.packages.core.trips.application.errors import AppError

router = APIRouter(prefix="/simulator/trips", tags=["monitoring", "simulator"])
capabilities_router = APIRouter(prefix="/simulator", tags=["simulator"])


@capabilities_router.get("/capabilities")
def get_simulator_capabilities(
    settings: Settings = Depends(get_settings),
) -> dict[str, bool]:
    return {"fault_injection_enabled": settings.simulator_fault_injection_enabled}


@router.post("/{trip_id}/start", response_model=SimulationState)
def start_simulation(
    trip_id: str,
    request: SimulatorStartRequest,
    user_id: str = Depends(get_current_user_id),
    service: MonitoringSimulatorService = Depends(get_monitoring_simulator_service),
    settings: Settings = Depends(get_settings),
) -> SimulationState:
    if request.simulation_fault != "NONE" and not settings.simulator_fault_injection_enabled:
        raise AppError(
            "SIMULATOR_FAULT_INJECTION_DISABLED",
            403,
            "Simulator fault injection is disabled.",
        )
    return service.start(trip_id, user_id, request)


@router.post("/{trip_id}/tick", response_model=SimulationState)
def tick_simulation(
    trip_id: str,
    user_id: str = Depends(get_current_user_id),
    service: MonitoringSimulatorService = Depends(get_monitoring_simulator_service),
) -> SimulationState:
    return service.tick(trip_id, user_id)


@router.get("/{trip_id}", response_model=SimulationState)
def get_simulation(
    trip_id: str,
    user_id: str = Depends(get_current_user_id),
    service: MonitoringSimulatorService = Depends(get_monitoring_simulator_service),
) -> SimulationState:
    return service.get_state(trip_id, user_id)


@router.post("/{trip_id}/pause", response_model=SimulationState)
def pause_simulation(
    trip_id: str,
    user_id: str = Depends(get_current_user_id),
    service: MonitoringSimulatorService = Depends(get_monitoring_simulator_service),
) -> SimulationState:
    return service.pause(trip_id, user_id)


@router.post("/{trip_id}/resume", response_model=SimulationState)
def resume_simulation(
    trip_id: str,
    user_id: str = Depends(get_current_user_id),
    service: MonitoringSimulatorService = Depends(get_monitoring_simulator_service),
) -> SimulationState:
    return service.resume(trip_id, user_id)


@router.post("/{trip_id}/reset", response_model=SimulationState)
def reset_simulation(
    trip_id: str,
    user_id: str = Depends(get_current_user_id),
    service: MonitoringSimulatorService = Depends(get_monitoring_simulator_service),
) -> SimulationState:
    return service.reset(trip_id, user_id)


@router.post("/{trip_id}/refresh-telemetry", response_model=SimulationState)
def refresh_simulation_telemetry(
    trip_id: str,
    user_id: str = Depends(get_current_user_id),
    service: MonitoringSimulatorService = Depends(get_monitoring_simulator_service),
) -> SimulationState:
    return service.refresh_telemetry(trip_id, user_id)


@router.post("/{trip_id}/activate-plan", response_model=SimulationState)
def activate_replanned_simulation_plan(
    trip_id: str,
    request: SimulatorStartRequest,
    user_id: str = Depends(get_current_user_id),
    service: MonitoringSimulatorService = Depends(get_monitoring_simulator_service),
) -> SimulationState:
    return service.activate_replanned_plan(trip_id, user_id, request)


@router.post("/{trip_id}/decision", response_model=SimulationState)
def decide_simulation(
    trip_id: str,
    request: SimulationDecisionRequest,
    user_id: str = Depends(get_current_user_id),
    service: MonitoringSimulatorService = Depends(get_monitoring_simulator_service),
) -> SimulationState:
    return service.decide(trip_id, user_id, request)

