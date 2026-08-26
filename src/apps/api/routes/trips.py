import json
from queue import Queue
from threading import Thread

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import StreamingResponse

from src.apps.api.bootstrap.config import Settings, get_settings
from src.packages.contracts.errors import ErrorEnvelope
from src.packages.contracts.trips import (
    AssumptionSnapshot,
    PlanDecisionResponse,
    PlanGenerationResponse,
    PlanListResponse,
    ReplanRequest,
    TripCreatedResponse,
    TripCreateRequest,
    TripDetailResponse,
    TripHistoryResponse,
)
from src.packages.core.auth.api.dependencies import get_auth_service, get_current_user_id
from src.packages.core.auth.application.service import AuthService
from src.packages.core.trips.api.dependencies import get_trip_service
from src.packages.core.trips.application.errors import AppError
from src.packages.core.trips.application.service import TripService

router = APIRouter(tags=["trips"])


def _expected_version(if_match: str | None) -> int:
    if if_match is None:
        raise AppError("PRECONDITION_REQUIRED", 428, "If-Match plan version is required.")
    try:
        return int(if_match.strip().strip('"'))
    except ValueError as exc:
        raise AppError("VALIDATION_ERROR", 400, "If-Match must be a plan version number.") from exc


@router.get("/config/assumptions", response_model=AssumptionSnapshot, tags=["configuration"])
def get_current_assumptions(
    vehicle_profile_id: str = "vinfast-vf6-plus-v1",
    trip_service: TripService = Depends(get_trip_service),
) -> AssumptionSnapshot:
    return trip_service.get_current_assumptions(vehicle_profile_id)


@router.post(
    "/trips",
    response_model=TripCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorEnvelope}, 409: {"model": ErrorEnvelope}},
)
def create_trip(
    request_body: TripCreateRequest,
    request: Request,
    response: Response,
    current_user_id: str = Depends(get_current_user_id),
    settings: Settings = Depends(get_settings),
    auth_service: AuthService = Depends(get_auth_service),
    trip_service: TripService = Depends(get_trip_service),
) -> TripCreatedResponse:
    if settings.app_env != "test":
        auth_service.require_owned_vehicle_profile(current_user_id, request_body.vehicle_profile_id)
    trip = trip_service.create_trip(request_body, owner_id=current_user_id)
    response.headers["X-Trace-Id"] = request.state.trace_id
    return trip


@router.get("/trips/history", response_model=TripHistoryResponse)
def list_trip_history(
    current_user_id: str = Depends(get_current_user_id),
    trip_service: TripService = Depends(get_trip_service),
) -> TripHistoryResponse:
    return trip_service.list_trip_history(owner_id=current_user_id)


@router.get(
    "/trips/{trip_id}",
    response_model=TripDetailResponse,
    responses={403: {"model": ErrorEnvelope}, 404: {"model": ErrorEnvelope}},
)
def get_trip(
    trip_id: str,
    request: Request,
    response: Response,
    current_user_id: str = Depends(get_current_user_id),
    trip_service: TripService = Depends(get_trip_service),
) -> TripDetailResponse:
    trip = trip_service.get_trip(trip_id, owner_id=current_user_id)
    response.headers["X-Trace-Id"] = request.state.trace_id
    return trip


@router.post("/plans/{plan_id}/confirm", response_model=PlanDecisionResponse)
def confirm_plan(
    plan_id: str,
    request: Request,
    current_user_id: str = Depends(get_current_user_id),
    trip_service: TripService = Depends(get_trip_service),
) -> PlanDecisionResponse:
    return trip_service.confirm_plan(
        plan_id,
        owner_id=current_user_id,
        expected_version=_expected_version(request.headers.get("If-Match")),
        ip_address=request.client.host if request.client else None,
    )


@router.post(
    "/trips/{trip_id}/plans",
    response_model=PlanGenerationResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        403: {"model": ErrorEnvelope},
        404: {"model": ErrorEnvelope},
        503: {"model": ErrorEnvelope},
    },
)
def create_trip_plan(
    trip_id: str,
    request: Request,
    response: Response,
    current_user_id: str = Depends(get_current_user_id),
    trip_service: TripService = Depends(get_trip_service),
) -> PlanGenerationResponse:
    plan_response = trip_service.generate_trip_plan(trip_id, owner_id=current_user_id)
    if plan_response.outcome != "PLAN_CREATED":
        response.status_code = status.HTTP_200_OK
    response.headers["X-Trace-Id"] = request.state.trace_id
    return plan_response


@router.post("/trips/{trip_id}/plans/replan", response_model=PlanGenerationResponse)
def replan_trip(
    trip_id: str,
    request_body: ReplanRequest,
    current_user_id: str = Depends(get_current_user_id),
    trip_service: TripService = Depends(get_trip_service),
) -> PlanGenerationResponse:
    # excluded_station_ids is part of the F3→F4 contract. F4 will apply it to station discovery.
    return trip_service.generate_trip_plan(
        trip_id, owner_id=current_user_id,
        current_lat=request_body.current_lat, current_lon=request_body.current_lon,
        current_soc_percent=request_body.current_soc_percent,
    )


@router.post("/trips/{trip_id}/plans/stream")
def stream_trip_plan(
    trip_id: str,
    current_user_id: str = Depends(get_current_user_id),
    trip_service: TripService = Depends(get_trip_service),
) -> StreamingResponse:
    events: Queue[dict] = Queue()

    def run() -> None:
        try:
            result = trip_service.generate_trip_plan(
                trip_id,
                owner_id=current_user_id,
                progress_callback=lambda message: events.put({"type": "progress", "message": message}),
            )
            events.put({"type": "result", "data": result.model_dump(mode="json")})
        except Exception as exc:
            events.put({"type": "error", "message": str(exc)})
        finally:
            events.put({"type": "done"})

    Thread(target=run, daemon=True).start()

    def body():
        while True:
            event = events.get()
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if event["type"] == "done":
                break

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/trips/{trip_id}/plans",
    response_model=PlanListResponse,
    responses={403: {"model": ErrorEnvelope}, 404: {"model": ErrorEnvelope}},
)
def list_trip_plans(
    trip_id: str,
    request: Request,
    response: Response,
    current_user_id: str = Depends(get_current_user_id),
    trip_service: TripService = Depends(get_trip_service),
) -> PlanListResponse:
    plans = trip_service.get_trip_plans(trip_id, owner_id=current_user_id)
    response.headers["X-Trace-Id"] = request.state.trace_id
    return plans
