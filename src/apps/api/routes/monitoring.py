from fastapi import APIRouter, Depends

from src.packages.contracts.monitoring import (
    SimulationDecisionRequest,
    SimulationState,
    SimulatorStartRequest,
)
from src.packages.core.auth.api.dependencies import get_current_user_id
from src.packages.core.monitoring.api.dependencies import get_monitoring_simulator_service
from src.packages.core.monitoring.application.service import MonitoringSimulatorService

router = APIRouter(prefix="/simulator/trips", tags=["monitoring", "simulator"])


@router.post("/{trip_id}/start", response_model=SimulationState)
def start_simulation(
    trip_id: str,
    request: SimulatorStartRequest,
    user_id: str = Depends(get_current_user_id),
    service: MonitoringSimulatorService = Depends(get_monitoring_simulator_service),
) -> SimulationState:
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


@router.post("/{trip_id}/decision", response_model=SimulationState)
def decide_simulation(
    trip_id: str,
    request: SimulationDecisionRequest,
    user_id: str = Depends(get_current_user_id),
    service: MonitoringSimulatorService = Depends(get_monitoring_simulator_service),
) -> SimulationState:
    return service.decide(trip_id, user_id, request)

