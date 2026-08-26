from __future__ import annotations

from fastapi import APIRouter, Depends, status

from src.packages.contracts.simulator import (
    SimulationCatalogResponse,
    SimulationRunResponse,
    SimulationStartRequest,
)
from src.packages.core.auth.api.dependencies import get_current_user_id
from src.packages.core.simulator.api.dependencies import get_simulator_service
from src.packages.core.simulator.application.simulator_service import SimulatorService
from src.packages.core.trips.application.errors import AppError

router = APIRouter(tags=["simulation"])


def _translate_error(exc: Exception) -> AppError:
    if isinstance(exc, PermissionError):
        return AppError("FORBIDDEN", 403, str(exc))
    if isinstance(exc, KeyError):
        return AppError("NOT_FOUND", 404, str(exc).strip("'"))
    return AppError("SIMULATION_NOT_READY", 409, str(exc))


@router.get("/simulation-cases", response_model=SimulationCatalogResponse)
def list_simulation_cases(
    _owner_id: str = Depends(get_current_user_id),
    service: SimulatorService = Depends(get_simulator_service),
) -> SimulationCatalogResponse:
    service.catalog.reload()
    return service.catalog.catalog()


@router.post(
    "/simulation-runs",
    response_model=SimulationRunResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_simulation(
    body: SimulationStartRequest,
    owner_id: str = Depends(get_current_user_id),
    service: SimulatorService = Depends(get_simulator_service),
) -> SimulationRunResponse:
    try:
        return service.start(owner_id, body)
    except (KeyError, ValueError) as exc:
        raise _translate_error(exc) from exc


@router.get("/simulation-runs/{run_id}", response_model=SimulationRunResponse)
def get_simulation(
    run_id: str,
    owner_id: str = Depends(get_current_user_id),
    service: SimulatorService = Depends(get_simulator_service),
) -> SimulationRunResponse:
    try:
        return service.get(owner_id, run_id)
    except (KeyError, PermissionError) as exc:
        raise _translate_error(exc) from exc


def _control(
    operation: str,
    run_id: str,
    owner_id: str,
    service: SimulatorService,
) -> SimulationRunResponse:
    try:
        return getattr(service, operation)(owner_id, run_id)
    except (KeyError, PermissionError, ValueError) as exc:
        raise _translate_error(exc) from exc


@router.post("/simulation-runs/{run_id}/step", response_model=SimulationRunResponse)
def step_simulation(
    run_id: str,
    owner_id: str = Depends(get_current_user_id),
    service: SimulatorService = Depends(get_simulator_service),
) -> SimulationRunResponse:
    return _control("step", run_id, owner_id, service)


@router.post("/simulation-runs/{run_id}/pause", response_model=SimulationRunResponse)
def pause_simulation(
    run_id: str,
    owner_id: str = Depends(get_current_user_id),
    service: SimulatorService = Depends(get_simulator_service),
) -> SimulationRunResponse:
    return _control("pause", run_id, owner_id, service)


@router.post("/simulation-runs/{run_id}/resume", response_model=SimulationRunResponse)
def resume_simulation(
    run_id: str,
    owner_id: str = Depends(get_current_user_id),
    service: SimulatorService = Depends(get_simulator_service),
) -> SimulationRunResponse:
    return _control("resume", run_id, owner_id, service)


@router.post("/simulation-runs/{run_id}/reset", response_model=SimulationRunResponse)
def reset_simulation(
    run_id: str,
    owner_id: str = Depends(get_current_user_id),
    service: SimulatorService = Depends(get_simulator_service),
) -> SimulationRunResponse:
    return _control("reset", run_id, owner_id, service)


@router.post("/simulation-runs/{run_id}/replan", response_model=SimulationRunResponse)
def apply_simulation_replan(
    run_id: str,
    owner_id: str = Depends(get_current_user_id),
    service: SimulatorService = Depends(get_simulator_service),
) -> SimulationRunResponse:
    return _control("replan", run_id, owner_id, service)


@router.post("/simulation-runs/{run_id}/refresh-telemetry", response_model=SimulationRunResponse)
def refresh_simulation_telemetry(
    run_id: str,
    owner_id: str = Depends(get_current_user_id),
    service: SimulatorService = Depends(get_simulator_service),
) -> SimulationRunResponse:
    return _control("refresh_telemetry", run_id, owner_id, service)
