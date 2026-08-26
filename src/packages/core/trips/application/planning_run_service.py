from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from src.packages.core.planning.application.orchestrator import (
    PlanningOrchestrator,
    PlanningRequest,
)
from src.packages.core.trips.domain.entities import PlanningRunRecord, TripStatus
from src.packages.core.trips.infrastructure.observability import metrics

logger = logging.getLogger(__name__)


class PlanningRunService:
    """Async-ready boundary around one deterministic planning execution."""

    def __init__(self, *, repository, orchestrator: PlanningOrchestrator):
        self._repository = repository
        self._orchestrator = orchestrator

    def create(
        self,
        *,
        trip_id: str,
        request_snapshot: dict,
        trace_id: str | None,
    ) -> PlanningRunRecord:
        run = PlanningRunRecord(
            id=str(uuid4()),
            trip_id=trip_id,
            status="QUEUED",
            request_snapshot_json=json.dumps(request_snapshot),
            trace_id=trace_id,
            started_at=None,
            finished_at=None,
            result_code=None,
            error_code=None,
            error_detail_json=None,
        )
        self._repository.create_planning_run(run)
        logger.info(
            "planning_run_queued",
            extra={"trip_id": trip_id, "planning_run_id": run.id, "trace_id": trace_id},
        )
        return run

    def execute(self, run_id: str, request: PlanningRequest):
        """Execute synchronously today; callable unchanged from a future worker."""
        persisted_run = self._repository.get_planning_run(run_id)
        trace_id = persisted_run.trace_id if persisted_run is not None else None
        started_at = datetime.now(UTC)
        started_clock = perf_counter()
        self._repository.mark_planning_run_running(run_id, started_at)
        self._repository.update_trip_status(request.trip_id, TripStatus.PLANNING.value)
        logger.info(
            "planning_run_started",
            extra={
                "trip_id": request.trip_id,
                "planning_run_id": run_id,
                "trace_id": trace_id,
                "provider": request.assumptions.routing_provider,
                "graph_version": request.assumptions.road_version,
                "station_dataset_generation": request.assumptions.station_dataset_generation,
                "energy_model_version": request.assumptions.energy_model_version,
                "policy_version": request.assumptions.policy_version,
            },
        )
        try:
            execution = self._orchestrator.plan(request)
        except Exception as exc:
            finished_at = datetime.now(UTC)
            self._repository.finish_planning_run(
                run_id,
                status="FAILED",
                result_code=None,
                error_code=type(exc).__name__,
                error_detail={"message": str(exc)},
                finished_at=finished_at,
            )
            self._repository.update_trip_status(
                request.trip_id, TripStatus.PLANNING_FAILED.value
            )
            logger.exception(
                "planning_run_failed",
                extra={
                    "trip_id": request.trip_id,
                    "planning_run_id": run_id,
                    "trace_id": trace_id,
                    "duration_ms": round((perf_counter() - started_clock) * 1000, 2),
                    "error_code": type(exc).__name__,
                },
            )
            metrics.observe(
                "planning_run_duration_ms",
                (perf_counter() - started_clock) * 1000,
                outcome="FAILED",
            )
            raise

        state = execution.state
        result_code = _result_code(state)
        current_trip = self._repository.get_trip(request.trip_id)
        has_confirmed_plan = bool(
            current_trip is not None and current_trip.confirmed_plan_version is not None
        )
        trip_status = (
            TripStatus.ACTIVE.value
            if has_confirmed_plan
            else TripStatus.PLANNED.value
            if state.get("plan_proposal") is not None
            else TripStatus.PLANNING_FAILED.value
        )
        finished_at = datetime.now(UTC)
        self._repository.finish_planning_run(
            run_id,
            status="SUCCEEDED",
            result_code=result_code,
            error_code=None,
            error_detail=None,
            finished_at=finished_at,
        )
        self._repository.update_trip_status(request.trip_id, trip_status)
        logger.info(
            "planning_run_completed",
            extra={
                "trip_id": request.trip_id,
                "planning_run_id": run_id,
                "trace_id": trace_id,
                "duration_ms": round((perf_counter() - started_clock) * 1000, 2),
                "result_code": result_code,
            },
        )
        metrics.observe(
            "planning_run_duration_ms",
            (perf_counter() - started_clock) * 1000,
            outcome=result_code,
        )
        metrics.increment("planner_outcome_total", outcome=result_code)
        return execution


def _result_code(state: dict) -> str:
    proposal = state.get("plan_proposal")
    if proposal is not None:
        if state.get("recovery_mode") or _conditional_reason_codes(proposal):
            return "CONDITIONAL"
        return "PLAN_CREATED"
    if state.get("station_routing_rate_limited") or state.get(
        "station_routing_budget_exhausted"
    ):
        return "ACTION_REQUIRED"
    if state.get("station_provider_unavailable"):
        return "STATION_DATA_UNAVAILABLE"
    if state.get("no_feasible_plan") is not None:
        return "INFEASIBLE"
    return "UNKNOWN"


def _conditional_reason_codes(proposal) -> set[str]:
    """Read risk codes from either a contract model or a serialized proposal."""
    if isinstance(proposal, dict):
        risk_assessment = proposal.get("risk_assessment")
    else:
        risk_assessment = getattr(proposal, "risk_assessment", None)
    if isinstance(risk_assessment, dict):
        reason_codes = risk_assessment.get("reason_codes", ())
    else:
        reason_codes = getattr(risk_assessment, "reason_codes", ())
    return {str(code) for code in reason_codes or ()} & {
        "STATION_BUSY",
        "UNVERIFIED_STATION_DATA",
        "ENVIRONMENT_DATA_FALLBACK",
    }
