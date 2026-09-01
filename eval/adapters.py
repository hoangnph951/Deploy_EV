"""Adapters that execute golden cases through the production F3/F4 contracts."""

from __future__ import annotations

import asyncio
import re
import time
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from eval.contracts import GoldenCase
from eval.local_app import EvaluationHarness
from src.packages.contracts.monitoring import MonitoringEvent
from src.packages.core.monitoring.application.service import MonitoringEvaluator
from src.packages.core.replanning.application.event_coordinator import EventCoordinator


class CasePrediction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    cohort: str
    events: list[str]
    constraints: dict[str, Any]
    selected_tools: list[str]
    outcome: str
    action: str | None
    lifecycle: str | None
    candidate_count: int = Field(ge=0)
    safety_violations: list[str]
    narrative: str | None
    supervisor_mode: Literal[
        "OPENAI",
        "SAFE_FALLBACK",
        "DETERMINISTIC_ORACLE",
    ]
    model: str | None
    prompt_version: str | None
    latency_ms: float = Field(ge=0)
    raw_contract: dict[str, Any]


class EvaluationAdapter(Protocol):
    async def execute(self, case: GoldenCase) -> CasePrediction: ...


_DYNAMIC_ID_KEYS = {
    "agent_run_id",
    "correlation_id",
    "diff_id",
    "epoch_id",
    "event_id",
    "idempotency_key",
    "plan_id",
    "run_id",
    "snapshot_id",
    "telemetry_snapshot_id",
    "trace_id",
    "trip_id",
    "user_id",
}
_PRIVATE_KEYS = {
    "authorization",
    "headers",
    "lat",
    "latitude",
    "lng",
    "lon",
    "longitude",
    "provider_payload",
    "raw_provider_payload",
    "x-user-id",
}


def sanitize_raw_contract(value: Any, *, key: str | None = None) -> Any:
    """Remove identity, precise location, auth, and unconstrained provider payloads."""

    normalized_key = key.casefold() if key else None
    if normalized_key in _PRIVATE_KEYS:
        return None
    if normalized_key in _DYNAMIC_ID_KEYS or (
        normalized_key is not None
        and normalized_key.endswith("_id")
        and normalized_key != "station_id"
    ):
        return "[SANITIZED_ID]"
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for item_key, item_value in value.items():
            if item_key.casefold() in _PRIVATE_KEYS:
                continue
            sanitized[item_key] = sanitize_raw_contract(item_value, key=item_key)
        return sanitized
    if isinstance(value, list):
        return [sanitize_raw_contract(item, key=key) for item in value]
    return value


def _safe_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:48]


def _prediction(
    case: GoldenCase,
    *,
    started_ns: int,
    events: list[str],
    constraints: dict[str, Any],
    selected_tools: list[str],
    outcome: str,
    action: str | None,
    lifecycle: str | None,
    candidate_count: int = 0,
    safety_violations: list[str] | None = None,
    narrative: str | None = None,
    supervisor_mode: str = "DETERMINISTIC_ORACLE",
    model: str | None = None,
    prompt_version: str | None = None,
    raw_contract: dict[str, Any] | None = None,
) -> CasePrediction:
    normalized_mode = (
        supervisor_mode
        if supervisor_mode in {"OPENAI", "SAFE_FALLBACK"}
        else "DETERMINISTIC_ORACLE"
    )
    return CasePrediction(
        case_id=case.case_id,
        cohort=case.source,
        events=events,
        constraints=constraints,
        selected_tools=selected_tools,
        outcome=outcome,
        action=action,
        lifecycle=lifecycle,
        candidate_count=candidate_count,
        safety_violations=sorted(set(safety_violations or [])),
        narrative=narrative,
        supervisor_mode=normalized_mode,
        model=model if normalized_mode == "OPENAI" else None,
        prompt_version=prompt_version if normalized_mode == "OPENAI" else None,
        latency_ms=(time.perf_counter_ns() - started_ns) / 1_000_000,
        raw_contract=sanitize_raw_contract(raw_contract or {}),
    )


async def _create_trip_and_plan(client, owner: str, *, confirm: bool = True):
    created = await client.post(
        "/api/v1/trips",
        headers={"X-User-Id": owner},
        json={
            "origin": {
                "address": "Ha Noi",
                "lat": None,
                "lng": None,
                "source_type": "MANUAL",
            },
            "destination": {
                "address": "Hoa Binh",
                "lat": None,
                "lng": None,
                "source_type": "MANUAL",
            },
            "initial_soc_percent": 85,
            "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1",
            "preference": "balanced",
        },
    )
    created.raise_for_status()
    trip_id = created.json()["trip_id"]
    planned = await client.post(
        f"/api/v1/trips/{trip_id}/plans",
        headers={"X-User-Id": owner},
    )
    planned.raise_for_status()
    plan = planned.json().get("plan")
    if plan is None:
        raise RuntimeError(f"Evaluation planning did not create a plan: {planned.json()}")
    if confirm:
        confirmed = await client.post(
            f"/api/v1/plans/{plan['plan_id']}/confirm",
            headers={"X-User-Id": owner, "If-Match": str(plan["version"])},
        )
        confirmed.raise_for_status()
    return trip_id, plan


class F3ClassifyAdapter:
    def __init__(self, _harness: EvaluationHarness):
        self.evaluator = MonitoringEvaluator()

    async def execute(self, case: GoldenCase) -> CasePrediction:
        started_ns = time.perf_counter_ns()
        outcome = self.evaluator.classify(**case.input_snapshot)
        events = [] if outcome == "NORMAL" else [outcome]
        action = None if outcome == "NORMAL" else "EMIT_EVENT"
        lifecycle = "RUNNING" if outcome == "NORMAL" else "AWAITING_DECISION"
        return _prediction(
            case,
            started_ns=started_ns,
            events=events,
            constraints={"strict_thresholds": True},
            selected_tools=[],
            outcome=outcome,
            action=action,
            lifecycle=lifecycle,
            raw_contract={"classification": outcome, "events": events},
        )


class F3ApiAdapter:
    def __init__(self, harness: EvaluationHarness):
        self.harness = harness

    async def execute(self, case: GoldenCase) -> CasePrediction:
        started_ns = time.perf_counter_ns()
        owner = f"eval-{_safe_slug(case.case_id)}"
        async with self.harness.client() as client:
            trip_id, plan = await _create_trip_and_plan(client, owner)
            snapshot = case.input_snapshot
            scenario = snapshot.get("scenario", "STALE_TELEMETRY")
            scenario_value = snapshot.get(
                "scenario_value",
                snapshot.get("silent_seconds", snapshot.get("age_seconds")),
            )
            start_payload: dict[str, Any] = {
                "plan_id": plan["plan_id"],
                "plan": plan,
                "scenario": scenario,
                "seed": snapshot.get("seed", 210),
                "speed_multiplier": 100,
            }
            if scenario_value is not None:
                start_payload["scenario_value"] = scenario_value
            started = await client.post(
                f"/api/v1/simulator/trips/{trip_id}/start",
                headers={"X-User-Id": owner},
                json=start_payload,
            )
            started.raise_for_status()
            state = started.json()
            for _ in range(100):
                if state.get("events") or state.get("status") == "AWAITING_DECISION":
                    break
                ticked = await client.post(
                    f"/api/v1/simulator/trips/{trip_id}/tick",
                    headers={"X-User-Id": owner},
                )
                ticked.raise_for_status()
                state = ticked.json()
            observed_events = [item["event_type"] for item in state.get("events", [])]
            selected_tools: list[str] = []
            action: str | None = None
            outcome = state.get("status", "UNKNOWN")
            final_state = state
            controls = snapshot.get("controls", [])
            if controls:
                for control in controls:
                    response = await client.post(
                        f"/api/v1/simulator/trips/{trip_id}/{control.casefold()}",
                        headers={"X-User-Id": owner},
                    )
                    response.raise_for_status()
                    final_state = response.json()
                outcome = "RESET" if "RESET" in controls else final_state["status"]
                action = "RESET_SIMULATION" if "RESET" in controls else None
            elif snapshot.get("refresh_requested"):
                refreshed = await client.post(
                    f"/api/v1/simulator/trips/{trip_id}/refresh-telemetry",
                    headers={"X-User-Id": owner},
                )
                refreshed.raise_for_status()
                final_state = refreshed.json()
                selected_tools.append("refresh_telemetry")
                outcome = "REFRESHED"
                action = "REFRESH_TELEMETRY"
            return _prediction(
                case,
                started_ns=started_ns,
                events=observed_events,
                constraints={
                    "status": final_state.get("status"),
                    "tick_count": final_state.get("tick_count"),
                    "event_count": len(final_state.get("events", [])),
                    "seed": final_state.get("seed"),
                    "candidate_mutated": False,
                },
                selected_tools=selected_tools,
                outcome=outcome,
                action=action,
                lifecycle=final_state.get("status"),
                raw_contract={
                    "start_status": started.status_code,
                    "final_status": final_state.get("status"),
                    "events": [
                        {"event_type": item["event_type"], "status": item["status"]}
                        for item in final_state.get("events", [])
                    ],
                },
            )


def _event_specs(case: GoldenCase) -> list[dict[str, Any]]:
    snapshot = case.input_snapshot
    if snapshot.get("events"):
        return list(snapshot["events"])
    return [
        {
            "event_type": snapshot.get("event_type", "ROUTE_DEVIATION"),
            "station_ids": snapshot.get("station_ids", []),
        }
    ]


def _lifecycle_from_outcome(payload: dict[str, Any]) -> str | None:
    action = (payload.get("action") or {}).get("action")
    context = payload.get("context") or {}
    if context.get("pending_plan_version") is not None:
        return "PENDING"
    if action == "REQUEST_NEW_TELEMETRY":
        return "AWAITING_TELEMETRY"
    if payload.get("status") in {
        "INFEASIBLE",
        "INSUFFICIENT_EVIDENCE",
        "SEARCH_EXHAUSTED",
    }:
        return "STOPPED"
    if action == "CONTINUE_CURRENT_PLAN":
        return "ACTIVE_CURRENT_PLAN"
    return None


def _supervisor_metadata(payload: dict[str, Any], harness: EvaluationHarness):
    sources = [
        item.get("response_source")
        for item in payload.get("decision_trace", [])
        if item.get("response_source")
    ]
    action_source = (payload.get("action") or {}).get("response_source")
    if action_source:
        sources.append(action_source)
    if "OPENAI" in sources:
        return (
            "OPENAI",
            harness.settings.openai_replanning_model,
            harness.settings.openai_replanning_prompt_version,
        )
    if "SAFE_FALLBACK" in sources or harness.supervisor_mode in {"fallback", "timeout"}:
        return "SAFE_FALLBACK", None, None
    return "DETERMINISTIC_ORACLE", None, None


class F4ReplanAdapter:
    def __init__(self, harness: EvaluationHarness):
        self.harness = harness

    async def execute(self, case: GoldenCase) -> CasePrediction:
        started_ns = time.perf_counter_ns()
        owner = f"eval-{_safe_slug(case.case_id)}"
        async with self.harness.client() as client:
            trip_id, plan = await _create_trip_and_plan(client, owner)
            before_plans = (
                await client.get(
                    f"/api/v1/trips/{trip_id}/plans",
                    headers={"X-User-Id": owner},
                )
            ).json()["plans"]
            snapshot = case.input_snapshot
            telemetry = snapshot.get("telemetry", {})
            freshness = telemetry.get("freshness", snapshot.get("freshness", "FRESH"))
            now = datetime.now(UTC).isoformat()
            event_specs = _event_specs(case)
            simulation_fault = snapshot.get("fault", "NONE")
            if simulation_fault == "NONE":
                if snapshot.get("planner_verdict") == "INSUFFICIENT_EVIDENCE":
                    simulation_fault = "F1_PROVIDER_FAILURE"
                elif snapshot.get("planner_verdict") == "INFEASIBLE":
                    simulation_fault = "F1_PROVEN_INFEASIBLE"
            telemetry_id = telemetry.get(
                "snapshot_id",
                snapshot.get("telemetry_snapshot_id", f"telemetry-{_safe_slug(case.case_id)}"),
            )
            request = {
                "simulation_fault": simulation_fault,
                "telemetry": {
                    "snapshot_id": telemetry_id,
                    "lat": telemetry.get("lat", 21.0),
                    "lon": telemetry.get("lon", 105.0),
                    "soc_percent": telemetry.get("soc_percent", 50.0),
                    "expected_soc_percent": telemetry.get("expected_soc_percent", 56.0),
                    "speed_kph": 0,
                    "distance_km": telemetry.get("distance_km", 1.0),
                    "progress_percent": 1.0,
                    "freshness": freshness,
                    "source": (
                        "SIMULATED" if simulation_fault != "NONE" else "REAL_GPS"
                    ),
                    "age_seconds": telemetry.get("age_seconds", 84 if freshness == "STALE" else 0),
                    "recorded_at": now,
                },
                "events": [
                    {
                        "event_id": item.get(
                            "event_id",
                            f"event-{_safe_slug(case.case_id)}-{index}",
                        ),
                        "trip_id": trip_id,
                        "event_type": item["event_type"],
                        "occurred_at": now,
                        "received_at": now,
                        "telemetry_snapshot_id": telemetry_id,
                        "related_plan_version": plan["version"],
                        "severity": "HIGH",
                        "evidence_refs": [],
                        "correlation_id": f"correlation-{_safe_slug(case.case_id)}",
                        "station_ids": item.get("station_ids", []),
                    }
                    for index, item in enumerate(event_specs, start=1)
                ],
            }
            response = await client.post(
                f"/api/v1/trips/{trip_id}/replans",
                headers={"X-User-Id": owner},
                json=request,
            )
            response.raise_for_status()
            payload = response.json()
            after_plans = (
                await client.get(
                    f"/api/v1/trips/{trip_id}/plans",
                    headers={"X-User-Id": owner},
                )
            ).json()["plans"]

        tool_runs = payload.get("tool_runs", [])
        selected_tools = [item["tool"] for item in tool_runs]
        candidate_count = max(0, len(after_plans) - len(before_plans))
        candidate = payload.get("candidate")
        station_ids = {
            station_id
            for item in event_specs
            for station_id in item.get("station_ids", [])
        }
        candidate_stations = {
            item.get("station_id")
            for item in ((candidate or {}).get("charging_stops") or [])
            if item.get("station_id")
        }
        violations: list[str] = []
        if station_ids.intersection(candidate_stations):
            violations.append("BLACKLISTED_STATION_IN_CANDIDATE")
        if freshness == "STALE" and (
            candidate_count or (payload.get("context") or {}).get("pending_plan_version")
        ):
            violations.append("STALE_TELEMETRY_MUTATED_CANDIDATE")
        if (
            (payload.get("action") or {}).get("action", "").startswith("PROPOSE")
            and not (payload.get("action") or {}).get("requires_owner_confirmation")
        ):
            violations.append("UNCONFIRMED_AUTO_APPLY")
        if payload.get("status") == "INFEASIBLE" and (
            candidate_count
            or (payload.get("context") or {}).get("pending_plan_version") is not None
            or (payload.get("action") or {}).get("action", "").startswith("PROPOSE")
        ):
            violations.append("INFEASIBLE_CANDIDATE_PROPOSED")
        supervisor_mode, model, prompt_version = _supervisor_metadata(
            payload,
            self.harness,
        )
        return _prediction(
            case,
            started_ns=started_ns,
            events=[item["event_type"] for item in event_specs],
            constraints={
                "context_version": (payload.get("context") or {}).get("context_version"),
                "pending_plan_version": (payload.get("context") or {}).get(
                    "pending_plan_version"
                ),
                "owner_confirmation_required": (payload.get("action") or {}).get(
                    "requires_owner_confirmation"
                ),
                "candidate_mutated": candidate_count > 0,
                "excluded_station_ids": sorted(station_ids),
            },
            selected_tools=selected_tools,
            outcome=payload["status"],
            action=(payload.get("action") or {}).get("action"),
            lifecycle=_lifecycle_from_outcome(payload),
            candidate_count=candidate_count,
            safety_violations=violations,
            narrative=(payload.get("action") or {}).get("user_message"),
            supervisor_mode=supervisor_mode,
            model=model,
            prompt_version=prompt_version,
            raw_contract={
                "http_status": response.status_code,
                "status": payload["status"],
                "action": {
                    "action": (payload.get("action") or {}).get("action"),
                    "reason_codes": (payload.get("action") or {}).get("reason_codes", []),
                    "limitations": (payload.get("action") or {}).get("limitations", []),
                    "requires_owner_confirmation": (payload.get("action") or {}).get(
                        "requires_owner_confirmation"
                    ),
                    "response_source": (payload.get("action") or {}).get(
                        "response_source"
                    ),
                },
                "context": {
                    "context_version": (payload.get("context") or {}).get(
                        "context_version"
                    ),
                    "pending_plan_version": (payload.get("context") or {}).get(
                        "pending_plan_version"
                    ),
                },
                "epoch": {
                    "event_count": len((payload.get("epoch") or {}).get("event_ids", [])),
                    "status": (payload.get("epoch") or {}).get("status"),
                },
                "tool_runs": [
                    {
                        "sequence": item.get("sequence"),
                        "tool": item.get("tool"),
                        "status": item.get("status"),
                        "provider": item.get("provider"),
                        "freshness": item.get("freshness"),
                        "reason_codes": item.get("reason_codes", []),
                    }
                    for item in tool_runs
                ],
                "candidate_present": candidate is not None,
                "candidate_count": candidate_count,
            },
        )


class F4LifecycleAdapter:
    def __init__(self, harness: EvaluationHarness):
        self.harness = harness

    async def execute(self, case: GoldenCase) -> CasePrediction:
        snapshot = case.input_snapshot
        if snapshot.get("event_ids"):
            started_ns = time.perf_counter_ns()
            now = datetime.now(UTC)
            event_id = snapshot["event_ids"][0]
            event = MonitoringEvent(
                event_id=event_id,
                trip_id="evaluation-trip",
                event_type=snapshot.get("event_type", "ROUTE_DEVIATION"),
                occurred_at=now,
                received_at=now,
                telemetry_snapshot_id="evaluation-snapshot",
                related_plan_version=1,
                severity="HIGH",
                correlation_id="evaluation-correlation",
            )
            coordination = EventCoordinator().coordinate(
                [event, event],
                context_version=snapshot.get("context_version", 1),
            )
            return _prediction(
                case,
                started_ns=started_ns,
                events=[item.event_type for item in coordination.events],
                constraints={
                    "epoch_event_count": len(coordination.epoch.event_ids),
                    "duplicate_event_count": len(coordination.duplicate_event_ids),
                },
                selected_tools=[],
                outcome="DEDUPLICATED",
                action="COALESCE_EVENT",
                lifecycle="COORDINATED",
                raw_contract={
                    "epoch_event_count": len(coordination.epoch.event_ids),
                    "duplicate_event_count": len(coordination.duplicate_event_ids),
                },
            )
        if snapshot.get("concurrent_decisions"):
            return await self._concurrent_confirm(case)
        if snapshot.get("owner_decision") == "REJECT":
            return await self._owner_reject(case)
        return await F4ReplanAdapter(self.harness).execute(case)

    async def _concurrent_confirm(self, case: GoldenCase) -> CasePrediction:
        started_ns = time.perf_counter_ns()
        owner = f"eval-{_safe_slug(case.case_id)}"
        async with self.harness.client() as client:
            trip_id, plan = await _create_trip_and_plan(client, owner, confirm=False)

            async def confirm():
                return await client.post(
                    f"/api/v1/trips/{trip_id}/plans/{plan['version']}/confirm",
                    headers={"X-User-Id": owner},
                    json={
                        "expected_plan_version": plan["version"],
                        "expected_context_version": 1,
                    },
                )

            responses = await asyncio.gather(confirm(), confirm())
        statuses = sorted(item.status_code for item in responses)
        return _prediction(
            case,
            started_ns=started_ns,
            events=[],
            constraints={
                "http_statuses": statuses,
                "success_count": statuses.count(200),
                "conflict_count": statuses.count(409),
            },
            selected_tools=[],
            outcome="VERSION_CONFLICT" if statuses == [200, 409] else "INVALID_RACE",
            action="CONFIRM_ONCE",
            lifecycle="CONFIRMED" if 200 in statuses else "PENDING",
            raw_contract={"http_statuses": statuses},
        )

    async def _owner_reject(self, case: GoldenCase) -> CasePrediction:
        started_ns = time.perf_counter_ns()
        owner = f"eval-{_safe_slug(case.case_id)}"
        async with self.harness.client() as client:
            trip_id, first = await _create_trip_and_plan(client, owner)
            second_response = await client.post(
                f"/api/v1/trips/{trip_id}/plans",
                headers={"X-User-Id": owner},
            )
            second_response.raise_for_status()
            second = second_response.json()["plan"]
            rejected = await client.post(
                f"/api/v1/plans/{second['plan_id']}/reject",
                headers={"X-User-Id": owner, "If-Match": str(second["version"])},
                json={"reason": case.input_snapshot.get("reason", "Rejected")},
            )
            rejected.raise_for_status()
            plans = (
                await client.get(
                    f"/api/v1/trips/{trip_id}/plans",
                    headers={"X-User-Id": owner},
                )
            ).json()["plans"]
        active = next(item for item in plans if item["version"] == first["version"])
        rejected_plan = next(item for item in plans if item["version"] == second["version"])
        violations = [] if active["status"] == "CONFIRMED" else ["ACTIVE_PLAN_MUTATED"]
        return _prediction(
            case,
            started_ns=started_ns,
            events=[],
            constraints={
                "confirmed_plan_version_after": first["version"],
                "rejected_plan_version": second["version"],
                "active_plan_mutated": bool(violations),
            },
            selected_tools=[],
            outcome=rejected_plan["status"],
            action="REJECT_CANDIDATE",
            lifecycle="ACTIVE",
            safety_violations=violations,
            raw_contract={
                "reject_http_status": rejected.status_code,
                "active_status": active["status"],
                "rejected_status": rejected_plan["status"],
            },
        )


class F4SecurityAdapter:
    def __init__(self, harness: EvaluationHarness):
        self.harness = harness

    async def execute(self, case: GoldenCase) -> CasePrediction:
        if "endpoint_set" not in case.input_snapshot:
            return await F4ReplanAdapter(self.harness).execute(case)
        started_ns = time.perf_counter_ns()
        owner = f"eval-owner-{_safe_slug(case.case_id)}"
        actor = f"eval-actor-{_safe_slug(case.case_id)}"
        async with self.harness.client() as client:
            trip_id, plan = await _create_trip_and_plan(client, owner, confirm=False)
            statuses: list[int] = []
            for endpoint in case.input_snapshot["endpoint_set"]:
                if endpoint == "F2_CONFIRM":
                    response = await client.post(
                        f"/api/v1/plans/{plan['plan_id']}/confirm",
                        headers={"X-User-Id": actor, "If-Match": str(plan["version"])},
                    )
                elif endpoint == "F2_REJECT":
                    response = await client.post(
                        f"/api/v1/plans/{plan['plan_id']}/reject",
                        headers={"X-User-Id": actor, "If-Match": str(plan["version"])},
                        json={"reason": "unauthorized"},
                    )
                else:
                    decision = endpoint.removeprefix("F4_").casefold()
                    response = await client.post(
                        f"/api/v1/trips/{trip_id}/plans/{plan['version']}/{decision}",
                        headers={"X-User-Id": actor},
                        json={
                            "expected_plan_version": plan["version"],
                            "expected_context_version": 1,
                        },
                    )
                statuses.append(response.status_code)
            owner_plans = (
                await client.get(
                    f"/api/v1/trips/{trip_id}/plans",
                    headers={"X-User-Id": owner},
                )
            ).json()["plans"]
        owner_plan = next(item for item in owner_plans if item["version"] == plan["version"])
        violations = [] if owner_plan["status"] == "PENDING" else ["CROSS_USER_MUTATION"]
        return _prediction(
            case,
            started_ns=started_ns,
            events=[],
            constraints={
                "http_statuses": statuses,
                "candidate_mutated": bool(violations),
                "owner_plan_status": owner_plan["status"],
            },
            selected_tools=[],
            outcome=(
                "FORBIDDEN" if statuses and all(item in {403, 404} for item in statuses)
                else "SECURITY_FAILURE"
            ),
            action="DENY_MUTATION",
            lifecycle=owner_plan["status"],
            safety_violations=violations,
            raw_contract={
                "http_statuses": statuses,
                "owner_plan_status": owner_plan["status"],
            },
        )


def adapter_for(case: GoldenCase, harness: EvaluationHarness) -> EvaluationAdapter:
    adapters: dict[str, type] = {
        "F3_CLASSIFY": F3ClassifyAdapter,
        "F3_API": F3ApiAdapter,
        "F4_REPLAN": F4ReplanAdapter,
        "F4_LIFECYCLE": F4LifecycleAdapter,
        "F4_SECURITY": F4SecurityAdapter,
    }
    return adapters[case.category](harness)


async def run_accuracy_cases(
    cases: list[GoldenCase],
    harness: EvaluationHarness,
) -> list[CasePrediction]:
    """Execute cases in order with isolated databases and supervisor budgets."""

    predictions: list[CasePrediction] = []
    for case in cases:
        case_harness = harness.isolated_for(case.case_id)
        try:
            predictions.append(await adapter_for(case, case_harness).execute(case))
        finally:
            case_harness.close(remove_database=True)
    return predictions
