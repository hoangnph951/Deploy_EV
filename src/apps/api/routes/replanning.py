from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from src.apps.api.bootstrap.config import Settings, get_settings
from src.packages.agent.replanning.fallback import ConservativeSupervisor
from src.packages.agent.replanning.openai_adapter import OpenAISupervisor
from src.packages.contracts.replanning import (
    PlanDecisionRequest,
    PlanDecisionResponse,
    ReplanSubmissionRequest,
)
from src.packages.core.auth.api.dependencies import get_current_user_id
from src.packages.core.monitoring.domain.geometry import haversine_km
from src.packages.core.replanning.api.dependencies import get_replanning_runtime_store
from src.packages.core.replanning.application.plan_diff import PlanDiffEngine, PlanMetrics
from src.packages.core.replanning.application.runtime import ReplanningRuntimeStore
from src.packages.core.replanning.application.service import ReplanningOutcome, ReplanningService
from src.packages.core.replanning.application.simulation_faults import (
    SimulationFaultCandidatePlanner,
)
from src.packages.core.trips.api.dependencies import get_trip_service
from src.packages.core.trips.application.errors import AppError
from src.packages.core.trips.application.service import TripService

router = APIRouter(tags=["replanning"])


def _get_plan_state(
    trip_service: TripService,
    trip_id: str,
    owner_id: str,
) -> tuple[int, int | None]:
    plans = trip_service.get_trip_plans(trip_id, owner_id=owner_id).plans
    pending_plan_version = max(
        (
            plan.version
            for plan in plans
            if plan.status in {"PENDING", "CONDITIONAL"}
        ),
        default=None,
    )
    return len(plans), pending_plan_version


def _build_supervisor(settings: Settings):
    if settings.app_env == "test":
        return ConservativeSupervisor()
    if not settings.openai_replanning_enabled:
        raise AppError(
            "AI_DECISION_SUPPORT_DISABLED", 503,
            "OpenAI replanning decision support is disabled.",
        )
    if not settings.openai_api_key.strip():
        raise AppError(
            "AI_DECISION_SUPPORT_NOT_CONFIGURED", 503,
            "OPENAI_API_KEY is required for replanning decisions.",
        )
    return OpenAISupervisor(
        api_key=settings.openai_api_key,
        model=settings.openai_replanning_model,
        base_url=settings.openai_base_url or None,
        timeout_seconds=settings.openai_replanning_timeout_seconds,
        max_turns=settings.replanning_max_llm_turns,
    )


def get_replanning_supervisor(settings: Settings = Depends(get_settings)):
    """Provide the configured supervisor at the API composition boundary."""

    return _build_supervisor(settings)


class TripServiceCandidatePlanner:
    def __init__(self, trip_service: TripService, owner_id: str):
        self.trip_service = trip_service
        self.owner_id = owner_id
        self._cached_f1_payload: dict | None = None

    def _confirmed_plan(self, trip_id: str, version: int):
        plans = self.trip_service.get_trip_plans(
            trip_id, owner_id=self.owner_id
        ).plans
        return next((plan for plan in plans if plan.version == version), None)

    def project_remaining_plan(self, **kwargs) -> dict:
        plan = self._confirmed_plan(
            kwargs["trip_id"], kwargs["base_plan_version"]
        )
        excluded = list(dict.fromkeys(kwargs["excluded_station_ids"]))
        traveled = max(0.0, float(kwargs["traveled_distance_km"] or 0.0))
        if plan is None:
            return {
                "confirmed_plan_version": kwargs["base_plan_version"],
                "traveled_distance_km": traveled,
                "remaining_station_ids": [],
                "original_station_ids": [],
                "affected_excluded_station_ids": [],
                "unaffected_remaining_station_ids": [],
                "station_unavailable_affects_remaining_trip": None,
                "remaining_distance_km": 0.0,
                "remaining_duration_min": 0.0,
                "remaining_min_soc_percent": 0.0,
                "final_soc_percent": 0.0,
            }
        remaining_stops = [
            stop for stop in plan.charging_stops
            if stop.distance_from_origin_km > traveled + 0.05
        ]
        remaining_ids = [stop.station_id for stop in remaining_stops]
        original_station_ids = [stop.station_id for stop in plan.charging_stops]
        affected = [station_id for station_id in excluded if station_id in remaining_ids]
        unaffected = [station_id for station_id in remaining_ids if station_id not in excluded]
        remaining_soc = [
            point.soc_percent for point in plan.soc_points
            if point.distance_km >= traveled
        ]
        remaining_distance = max(0.0, plan.route.distance_km - traveled)
        duration_ratio = (
            remaining_distance / plan.route.distance_km
            if plan.route.distance_km > 0 else 0.0
        )
        return {
            "confirmed_plan_version": plan.version,
            "traveled_distance_km": round(traveled, 3),
            "remaining_station_ids": remaining_ids,
            "original_station_ids": original_station_ids,
            "affected_excluded_station_ids": affected,
            "unaffected_remaining_station_ids": unaffected,
            "station_unavailable_affects_remaining_trip": (
                bool(affected) if excluded else None
            ),
            "remaining_distance_km": round(remaining_distance, 3),
            "remaining_duration_min": round(plan.route.duration_min * duration_ratio, 3),
            "remaining_min_soc_percent": min(remaining_soc or [plan.final_arrival_soc_percent]),
            "final_soc_percent": plan.final_arrival_soc_percent,
        }

    def build_candidate(self, **kwargs) -> dict:
        strategy = kwargs.get("strategy", "FULL_REPLAN")
        projection = kwargs.get("current_plan_projection") or {}
        replacement_required = bool(
            strategy == "MINIMAL_SUBSTITUTION"
            and projection.get("affected_excluded_station_ids")
        )
        if self._cached_f1_payload is None:
            response = self.trip_service.generate_trip_plan(
                kwargs["trip_id"], owner_id=self.owner_id,
                current_lat=kwargs["current_lat"], current_lon=kwargs["current_lon"],
                current_soc_percent=kwargs["current_soc_percent"],
                excluded_station_ids=kwargs["excluded_station_ids"],
                preferred_station_ids=(
                    kwargs.get("unaffected_remaining_station_ids", [])
                    if strategy == "MINIMAL_SUBSTITUTION" else None
                ),
                require_station_substitution=replacement_required,
                trigger_reason="F4_REPLAN",
            )
            self._cached_f1_payload = response.model_dump(mode="json")
        payload = self._cached_f1_payload
        if payload.get("outcome") == "INFEASIBLE":
            if strategy == "MINIMAL_SUBSTITUTION":
                return {
                    "feasibility_verdict": "STRATEGY_NOT_SATISFIED",
                    "strategy": strategy,
                    "outcome": payload,
                }
            return {
                "feasibility_verdict": "INFEASIBLE",
                "strategy": strategy,
                "outcome": payload,
            }
        if payload.get("outcome") in {"ACTION_REQUIRED"}:
            if payload.get("provider_status") == "VALIDATION_BUDGET_EXHAUSTED":
                return {
                    "feasibility_verdict": "SEARCH_EXHAUSTED",
                    "strategy": strategy,
                    "outcome": payload,
                }
            return {
                "feasibility_verdict": "INSUFFICIENT_EVIDENCE",
                "strategy": strategy,
                "outcome": payload,
            }
        plan = payload.get("plan") or {}
        candidate_station_ids = [
            stop.get("station_id") for stop in plan.get("charging_stops", [])
            if stop.get("station_id")
        ]
        blacklisted_in_candidate = sorted(
            set(kwargs["excluded_station_ids"]).intersection(candidate_station_ids)
        )
        route_polyline = (plan.get("route") or {}).get("polyline") or []
        origin_gap_km = None
        if route_polyline:
            origin_gap_km = haversine_km(
                (float(kwargs["current_lat"]), float(kwargs["current_lon"])),
                (float(route_polyline[0][0]), float(route_polyline[0][1])),
            )
        if blacklisted_in_candidate or origin_gap_km is None or origin_gap_km > 2.0:
            return {
                "feasibility_verdict": (
                    "STRATEGY_NOT_SATISFIED"
                    if strategy == "MINIMAL_SUBSTITUTION"
                    else "INSUFFICIENT_EVIDENCE"
                ),
                "strategy": strategy,
                "outcome": payload,
                "validation_reason": (
                    "BLACKLISTED_STATION_IN_CANDIDATE"
                    if blacklisted_in_candidate else "REPLAN_ORIGIN_MISMATCH"
                ),
                "blacklisted_station_ids": blacklisted_in_candidate,
                "origin_gap_km": round(origin_gap_km, 3) if origin_gap_km is not None else None,
            }
        if strategy == "MINIMAL_SUBSTITUTION":
            selected = self._select_minimal_substitution(
                [plan],
                unaffected_station_ids=kwargs.get("unaffected_remaining_station_ids", []),
                excluded_station_ids=kwargs["excluded_station_ids"],
                replacement_required=replacement_required,
                original_station_ids=projection.get("original_station_ids", []),
            )
            if selected is None:
                return {
                    "feasibility_verdict": "STRATEGY_NOT_SATISFIED",
                    "strategy": strategy,
                    "outcome": payload,
                }
            plan = selected
            payload = {**payload, "plan": selected}
        result = {
            "feasibility_verdict": plan.get("risk_assessment", {}).get("verdict", "FEASIBLE"),
            "plan_version": plan.get("version"), "outcome": payload,
            "strategy": strategy,
        }
        old_plan = self._confirmed_plan(kwargs["trip_id"], kwargs["base_plan_version"])
        if old_plan is not None and plan:
            old_metrics = PlanMetrics(
                distance_km=float(projection["remaining_distance_km"]),
                duration_min=float(projection["remaining_duration_min"]),
                final_soc_percent=float(projection["final_soc_percent"]),
                min_soc_percent=float(projection["remaining_min_soc_percent"]),
                station_ids=list(kwargs.get("remaining_station_ids", [])),
            )
            candidate_metrics = PlanMetrics(
                distance_km=plan["route"]["distance_km"],
                duration_min=plan["route"]["duration_min"],
                final_soc_percent=plan["final_arrival_soc_percent"],
                min_soc_percent=min(point["soc_percent"] for point in plan["soc_points"]),
                station_ids=[stop["station_id"] for stop in plan["charging_stops"]],
            )
            result["plan_diff"] = PlanDiffEngine().compare(
                old_metrics, candidate_metrics
            ).model_dump(mode="json")
        return result

    @staticmethod
    def _select_minimal_substitution(
        plans: list[dict], *, unaffected_station_ids: list[str],
        excluded_station_ids: list[str], replacement_required: bool = False,
        original_station_ids: list[str] | None = None,
    ) -> dict | None:
        excluded = set(excluded_station_ids)
        unaffected = list(unaffected_station_ids)
        original = set(original_station_ids or [])
        eligible: list[tuple[int, int, dict]] = []
        for plan in plans:
            risk = plan.get("risk_assessment") or {}
            station_ids = [
                stop.get("station_id") for stop in plan.get("charging_stops", [])
                if stop.get("station_id")
            ]
            if risk.get("verdict") != "FEASIBLE" or not risk.get("is_feasible", True):
                continue
            if excluded.intersection(station_ids):
                continue
            preserved = [station_id for station_id in station_ids if station_id in unaffected]
            if preserved != unaffected:
                continue
            added_count = sum(station_id not in unaffected for station_id in station_ids)
            replacement_count = sum(station_id not in original for station_id in station_ids)
            if replacement_required and replacement_count == 0:
                continue
            eligible.append((added_count, len(station_ids), plan))
        return min(eligible, key=lambda item: (item[0], item[1]))[2] if eligible else None


def _candidate_planner(
    trip_service: TripService,
    owner_id: str,
    body: ReplanSubmissionRequest,
    settings: Settings,
):
    delegate = TripServiceCandidatePlanner(trip_service, owner_id)
    if body.simulation_fault == "NONE":
        return delegate
    if not settings.simulator_fault_injection_enabled:
        raise AppError(
            "SIMULATOR_FAULT_INJECTION_DISABLED",
            403,
            "Simulator fault injection is disabled.",
        )
    if body.telemetry.source != "SIMULATED":
        raise AppError(
            "SIMULATOR_FAULT_REQUIRES_SIMULATED_TELEMETRY",
            422,
            "Fault injection is allowed only for simulated telemetry.",
        )
    return SimulationFaultCandidatePlanner(delegate, body.simulation_fault)


@router.post(
    "/trips/{trip_id}/replans",
    response_model=ReplanningOutcome,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_replan(
    trip_id: str,
    body: ReplanSubmissionRequest,
    owner_id: str = Depends(get_current_user_id),
    trip_service: TripService = Depends(get_trip_service),
    store: ReplanningRuntimeStore = Depends(get_replanning_runtime_store),
    settings: Settings = Depends(get_settings),
    supervisor=Depends(get_replanning_supervisor),
) -> ReplanningOutcome:
    trip = trip_service.get_trip(trip_id, owner_id=owner_id)
    if any(item.trip_id != trip_id for item in body.events):
        from src.packages.core.trips.application.errors import AppError
        raise AppError("EVENT_TRIP_MISMATCH", 409, "Monitoring event does not belong to this trip.")
    event_ids = ",".join(sorted(item.event_id for item in body.events))
    base_version = max(item.related_plan_version for item in body.events)
    idempotency_key = (
        f"{trip_id}:{body.telemetry.snapshot_id}:{base_version}:{event_ids}"
    )
    existing = store.find_idempotent(idempotency_key, owner_id)
    if existing is not None:
        return existing
    plan_count, pending_plan_version = _get_plan_state(trip_service, trip_id, owner_id)
    previous = store.initial_context(
        trip,
        plan_count,
        pending_plan_version=pending_plan_version,
    )
    outcome = ReplanningService(
        planner=_candidate_planner(trip_service, owner_id, body, settings),
        supervisor=supervisor,
    ).process(previous_context=previous, telemetry=body.telemetry, events=body.events)
    if previous.pending_plan_version is not None:
        trip_service.stale_pending_plan(
            trip_id, owner_id, previous.pending_plan_version
        )
    store.save(owner_id, outcome, body.events)
    store.bind_idempotency(idempotency_key, outcome.agent_run_id)
    return outcome


@router.post("/trips/{trip_id}/replans/stream")
async def stream_replan(
    trip_id: str,
    body: ReplanSubmissionRequest,
    owner_id: str = Depends(get_current_user_id),
    trip_service: TripService = Depends(get_trip_service),
    store: ReplanningRuntimeStore = Depends(get_replanning_runtime_store),
    settings: Settings = Depends(get_settings),
    supervisor=Depends(get_replanning_supervisor),
) -> StreamingResponse:
    trip = trip_service.get_trip(trip_id, owner_id=owner_id)
    if any(item.trip_id != trip_id for item in body.events):
        from src.packages.core.trips.application.errors import AppError
        raise AppError("EVENT_TRIP_MISMATCH", 409, "Monitoring event does not belong to this trip.")
    event_ids = ",".join(sorted(item.event_id for item in body.events))
    base_version = max(item.related_plan_version for item in body.events)
    idempotency_key = f"{trip_id}:{body.telemetry.snapshot_id}:{base_version}:{event_ids}"
    existing = store.find_idempotent(idempotency_key, owner_id)
    plan_count, pending_plan_version = _get_plan_state(trip_service, trip_id, owner_id)
    previous = store.initial_context(
        trip,
        plan_count,
        pending_plan_version=pending_plan_version,
    )
    planner = _candidate_planner(trip_service, owner_id, body, settings)
    event_loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict] = asyncio.Queue()

    def emit_trace(item) -> None:
        event_loop.call_soon_threadsafe(queue.put_nowait, {
            "type": "trace", "trace": item.model_dump(mode="json"),
        })

    def execute() -> None:
        try:
            if existing is not None:
                outcome = existing
            else:
                outcome = ReplanningService(
                    planner=planner,
                    supervisor=supervisor,
                    on_trace=emit_trace,
                ).process(
                    previous_context=previous,
                    telemetry=body.telemetry,
                    events=body.events,
                )
                if previous.pending_plan_version is not None:
                    trip_service.stale_pending_plan(
                        trip_id, owner_id, previous.pending_plan_version
                    )
                store.save(owner_id, outcome, body.events)
                store.bind_idempotency(idempotency_key, outcome.agent_run_id)
            event_loop.call_soon_threadsafe(queue.put_nowait, {
                "type": "complete", "outcome": outcome.model_dump(mode="json"),
            })
        except Exception as exc:
            event_loop.call_soon_threadsafe(queue.put_nowait, {
                "type": "error", "message": str(exc),
            })

    async def event_stream():
        task = asyncio.create_task(asyncio.to_thread(execute))
        while True:
            event = await queue.get()
            yield json.dumps(event, ensure_ascii=False, default=str) + "\n"
            if event["type"] in {"complete", "error"}:
                break
        await task

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/agent-runs/{agent_run_id}", response_model=ReplanningOutcome)
def get_agent_run(
    agent_run_id: str,
    owner_id: str = Depends(get_current_user_id),
    store: ReplanningRuntimeStore = Depends(get_replanning_runtime_store),
) -> ReplanningOutcome:
    return store.get_run(agent_run_id, owner_id)


@router.get("/planning-runs/{run_id}", response_model=ReplanningOutcome)
def get_planning_run(
    run_id: str,
    owner_id: str = Depends(get_current_user_id),
    store: ReplanningRuntimeStore = Depends(get_replanning_runtime_store),
) -> ReplanningOutcome:
    return store.get_run(run_id, owner_id)


@router.get("/trips/{trip_id}/context")
def get_trip_context(
    trip_id: str,
    owner_id: str = Depends(get_current_user_id),
    store: ReplanningRuntimeStore = Depends(get_replanning_runtime_store),
):
    return store.get_context(trip_id, owner_id)


@router.get("/trips/{trip_id}/events")
def get_trip_events(
    trip_id: str,
    owner_id: str = Depends(get_current_user_id),
    store: ReplanningRuntimeStore = Depends(get_replanning_runtime_store),
):
    return store.get_events(trip_id, owner_id)


@router.get("/trips/{trip_id}/decision-epochs/{epoch_id}")
def get_decision_epoch(
    trip_id: str,
    epoch_id: str,
    owner_id: str = Depends(get_current_user_id),
    store: ReplanningRuntimeStore = Depends(get_replanning_runtime_store),
):
    return store.get_epoch(trip_id, epoch_id, owner_id)


@router.get("/trips/{trip_id}/plan-diffs/{diff_id}")
def get_plan_diff(
    trip_id: str,
    diff_id: str,
    owner_id: str = Depends(get_current_user_id),
    store: ReplanningRuntimeStore = Depends(get_replanning_runtime_store),
):
    store.authorize_trip(trip_id, owner_id)
    for stored in store.runs.values():
        outcome = stored.outcome
        if outcome.context.trip_id == trip_id and outcome.plan_diff_id == diff_id:
            return outcome.plan_diff
    from src.packages.core.trips.application.errors import NotFoundError
    raise NotFoundError("PlanDiff")


@router.post(
    "/trips/{trip_id}/plans/{version}/confirm",
    response_model=PlanDecisionResponse,
)
def confirm_plan(
    trip_id: str,
    version: int,
    body: PlanDecisionRequest,
    owner_id: str = Depends(get_current_user_id),
    trip_service: TripService = Depends(get_trip_service),
    store: ReplanningRuntimeStore = Depends(get_replanning_runtime_store),
) -> PlanDecisionResponse:
    trip = trip_service.get_trip(trip_id, owner_id=owner_id)
    plan_count, pending_plan_version = _get_plan_state(trip_service, trip_id, owner_id)
    context = store.initial_context(
        trip,
        plan_count,
        pending_plan_version=pending_plan_version,
    )
    if body.expected_plan_version != version or body.expected_context_version != context.context_version:
        from src.packages.core.trips.application.errors import AppError
        raise AppError(
            "PLAN_CONTEXT_CHANGED", 409,
            "Trip context changed before plan confirmation.",
            {"current_context_version": context.context_version},
        )
    trip_service.decide_plan(trip_id, owner_id, version, "CONFIRMED")
    context.current_confirmed_plan_version = version
    if context.pending_plan_version == version:
        context.pending_plan_version = None
    return PlanDecisionResponse(
        trip_id=trip_id, plan_version=version,
        context_version=context.context_version, status="CONFIRMED",
    )


@router.post(
    "/trips/{trip_id}/plans/{version}/reject",
    response_model=PlanDecisionResponse,
)
def reject_plan(
    trip_id: str,
    version: int,
    body: PlanDecisionRequest,
    owner_id: str = Depends(get_current_user_id),
    trip_service: TripService = Depends(get_trip_service),
    store: ReplanningRuntimeStore = Depends(get_replanning_runtime_store),
) -> PlanDecisionResponse:
    trip = trip_service.get_trip(trip_id, owner_id=owner_id)
    plan_count, pending_plan_version = _get_plan_state(trip_service, trip_id, owner_id)
    context = store.initial_context(
        trip,
        plan_count,
        pending_plan_version=pending_plan_version,
    )
    if body.expected_plan_version != version or body.expected_context_version != context.context_version:
        from src.packages.core.trips.application.errors import AppError
        raise AppError("PLAN_CONTEXT_CHANGED", 409, "Trip context changed before rejection.")
    trip_service.decide_plan(trip_id, owner_id, version, "REJECTED")
    if context.pending_plan_version == version:
        context.pending_plan_version = None
    return PlanDecisionResponse(
        trip_id=trip_id, plan_version=version,
        context_version=context.context_version, status="REJECTED",
    )
