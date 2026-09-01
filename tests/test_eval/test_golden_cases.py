import json
import re
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest

from eval.dataset import load_golden_cases
from src.apps.api.routes.replanning import TripServiceCandidatePlanner
from src.packages.agent.replanning.fallback import ConservativeSupervisor
from src.packages.agent.replanning.schemas import ActionProposalDraft
from src.packages.contracts.monitoring import MonitoringEvent, TelemetrySnapshot
from src.packages.contracts.replanning import ActiveConstraintContext, TripContextSnapshot
from src.packages.core.monitoring.application.service import MonitoringEvaluator
from src.packages.core.replanning.application.service import ReplanningService

GOLDEN_V1 = (
    Path(__file__).resolve().parents[2]
    / "eval"
    / "datasets"
    / "f3_f4_golden_v1.jsonl"
)
CHANGELOG = GOLDEN_V1.with_name("CHANGELOG.md")
MENTOR_REMEDIATION_IDS = {
    "P210-F3-EDGE-002",
    "P210-F3-EDGE-003",
    "P210-F3-HAPPY-004",
    "P210-F3-EDGE-005",
    "P210-F3-EDGE-006",
    "P210-F4-HAPPY-001",
    "P210-F4-HAPPY-002",
    "P210-F4-EDGE-003",
    "P210-F4-UNHAPPY-005",
    "P210-F4-HAPPY-006",
    "P210-F4-EDGE-007",
    "P210-F4-SEC-008",
    "P210-F4-AI-009",
    "P210-F4-AI-904",
    "P210-F4-AI-905",
}


def _cases():
    return load_golden_cases(GOLDEN_V1)


def _case(case_id):
    return next(case for case in _cases() if case.case_id == case_id)


def _invoke_external_semantic_contracts():
    local_prefix = "tests/test_eval/test_golden_cases.py::"
    contracts = sorted({
        case.ground_truth_method
        for case in _cases()
        if case.category != "F3_CLASSIFY"
        and not case.ground_truth_method.startswith(local_prefix)
    })
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *contracts],
        cwd=GOLDEN_V1.parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return set(contracts)


def test_golden_v1_has_exact_cohort_composition():
    cases = _cases()
    counts = Counter(case.source for case in cases)

    assert len(cases) == 60
    assert counts == {
        "MENTOR_REMEDIATION": 15,
        "BOUNDARY": 21,
        "FAILURE_LIFECYCLE": 12,
        "HOLDOUT": 12,
    }


def test_golden_v1_has_exact_mentor_remediation_ids():
    actual = {case.case_id for case in _cases() if case.source == "MENTOR_REMEDIATION"}

    assert actual == MENTOR_REMEDIATION_IDS


def test_each_threshold_has_below_equal_above_cases():
    cases = [
        case
        for case in _cases()
        if case.source == "BOUNDARY" and case.category == "F3_CLASSIFY"
    ]

    for field, values in {
        "off_route_distance_km": {1.99, 2.0, 2.01},
        "soc_deficit_percent": {4.9, 5.0, 5.1},
        "silent_seconds": {59, 60, 61},
    }.items():
        assert values <= {case.input_snapshot.get(field) for case in cases}


def test_f3_classification_labels_execute_against_monitoring_oracle():
    evaluator = MonitoringEvaluator()
    cases = [case for case in _cases() if case.category == "F3_CLASSIFY"]

    for case in cases:
        actual = evaluator.classify(**case.input_snapshot)
        assert actual == case.expected_outcome, case.case_id
        assert case.expected_events == ([] if actual == "NORMAL" else [actual])


def test_boundary_equality_is_normal():
    equality = next(case for case in _cases() if case.case_id == "BOUNDARY-ALL-EQUAL")

    assert equality.input_snapshot == {
        "off_route_distance_km": 2.0,
        "silent_seconds": 60,
        "soc_deficit_percent": 5.0,
        "station_unavailable": False,
    }
    assert equality.expected_outcome == "NORMAL"
    assert equality.expected_events == []


def test_holdout_inputs_do_not_duplicate_non_holdout_inputs():
    cases = _cases()

    def fingerprint(case):
        payload = {"category": case.category, "input_snapshot": case.input_snapshot}
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    holdout = [fingerprint(case) for case in cases if case.source == "HOLDOUT"]
    non_holdout = {fingerprint(case) for case in cases if case.source != "HOLDOUT"}

    assert len(holdout) == 12
    assert len(set(holdout)) == len(holdout)
    assert set(holdout).isdisjoint(non_holdout)


class _SemanticPlanner:
    def __init__(self, verdict="FEASIBLE", *, projection=None, strategy_verdicts=None):
        self.verdict = verdict
        self.calls = []
        self.projection = projection or {
            "remaining_station_ids": ["ST-10"],
            "affected_excluded_station_ids": ["ST-10"],
            "unaffected_remaining_station_ids": [],
            "station_unavailable_affects_remaining_trip": True,
        }
        self.strategy_verdicts = strategy_verdicts or {}

    def project_remaining_plan(self, **_kwargs):
        return self.projection

    def build_candidate(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "plan_version": 5,
            "feasibility_verdict": self.strategy_verdicts.get(
                kwargs.get("strategy"), self.verdict
            ),
            "strategy": kwargs.get("strategy"),
            "plan_diff": {
                "distance_delta_km": 2.0,
                "duration_delta_min": 3.0,
                "final_soc_delta_percent": 4.0,
                "reserve_margin_delta_percent": 4.0,
                "removed_station_ids": ["ST-10"],
                "added_station_ids": ["ST-20"],
            },
        }


class _DraftingSupervisor(ConservativeSupervisor):
    def __init__(self, action, *, requires_owner_confirmation):
        self.action = action
        self.requires_owner_confirmation = requires_owner_confirmation

    def draft_action(self, **_kwargs):
        return ActionProposalDraft(
            action=self.action,
            reason_codes=["GOLDEN_SEMANTIC_ORACLE"],
            evidence_refs=["golden:semantic-oracle"],
            user_message="Executable golden semantic oracle.",
            limitations=[],
            requires_owner_confirmation=self.requires_owner_confirmation,
        )


def _replanning_execution(case_id):
    case = _case(case_id)
    snapshot = case.input_snapshot
    telemetry_data = snapshot.get("telemetry", {})
    freshness = telemetry_data.get("freshness", snapshot.get("freshness", "FRESH"))
    now = datetime(2026, 9, 1, tzinfo=UTC)
    telemetry = TelemetrySnapshot(
        snapshot_id=telemetry_data.get("snapshot_id", "golden-snapshot"),
        lat=telemetry_data.get("lat", 21.0),
        lon=telemetry_data.get("lon", 105.0),
        soc_percent=telemetry_data.get("soc_percent", 40.0),
        expected_soc_percent=telemetry_data.get("expected_soc_percent", 48.0),
        speed_kph=0,
        distance_km=30,
        progress_percent=20,
        freshness=freshness,
        age_seconds=telemetry_data.get("age_seconds", 61 if freshness == "STALE" else 0),
        recorded_at=now,
    )
    event_specs = snapshot.get("events") or [{
        "event_id": f"event-{case_id}",
        "event_type": snapshot["event_type"],
    }]
    events = [
        MonitoringEvent(
            event_id=item["event_id"],
            trip_id="golden-trip",
            event_type=item["event_type"],
            occurred_at=now,
            received_at=now,
            telemetry_snapshot_id=telemetry.snapshot_id,
            related_plan_version=3,
            severity="HIGH",
            evidence_refs=[item["event_id"]],
            correlation_id="golden-correlation",
            station_ids=item.get("station_ids", []),
        )
        for item in event_specs
    ]
    context = TripContextSnapshot(
        trip_id="golden-trip",
        context_version=4,
        current_confirmed_plan_version=3,
        pending_plan_version=None,
        telemetry_snapshot_id="previous-snapshot",
        current_lat=21.0,
        current_lng=105.0,
        current_soc_percent=50,
        destination_lat=18.7,
        destination_lng=105.7,
        vehicle_profile_version="vf6-v1",
        policy_version="policy-v1",
        assumption_snapshot_id="assumption-v1",
        active_event_ids=[],
        unresolved_constraints=ActiveConstraintContext(),
        created_at=now,
    )
    verdict = snapshot.get("planner_verdict", "FEASIBLE")
    if snapshot.get("fault") == "F1_PROVIDER_FAILURE":
        verdict = "INSUFFICIENT_EVIDENCE"
    elif snapshot.get("fault") == "F1_PROVEN_INFEASIBLE":
        verdict = "INFEASIBLE"
    supervisor = None
    if case_id == "P210-F4-HAPPY-006":
        supervisor = _DraftingSupervisor(
            "PROPOSE_CONDITIONAL_REPLAN", requires_owner_confirmation=True
        )
    elif case_id in {"FAILURE-STALE-GUARD-012", "HOLDOUT-F4-ACTION-GUARD-012"}:
        supervisor = _DraftingSupervisor(
            "PROPOSE_REPLAN", requires_owner_confirmation=False
        )
    projection = None
    if snapshot.get("station_position") == "BEHIND":
        projection = {
            "remaining_station_ids": snapshot.get("remaining_station_ids", ["ST-20"]),
            "affected_excluded_station_ids": [],
            "unaffected_remaining_station_ids": snapshot.get(
                "remaining_station_ids", ["ST-20"]
            ),
            "station_unavailable_affects_remaining_trip": False,
        }
    strategy_verdicts = None
    if case_id == "P210-F4-HAPPY-002":
        strategy_verdicts = {
            "MINIMAL_SUBSTITUTION": "STRATEGY_NOT_SATISFIED",
            "FULL_REPLAN": "FEASIBLE",
        }
    planner = _SemanticPlanner(
        verdict, projection=projection, strategy_verdicts=strategy_verdicts
    )
    outcome = ReplanningService(planner=planner, supervisor=supervisor).process(
        previous_context=context, telemetry=telemetry, events=events
    )
    return outcome, planner, events


def _replanning_outcome(case_id):
    return _replanning_execution(case_id)[0]


def _replanning_observation(case_id):
    outcome, planner, events = _replanning_execution(case_id)
    actual_tools = {run.tool for run in outcome.tool_runs}
    excluded_station_ids = []
    for call in planner.calls:
        excluded_station_ids.extend(call.get("excluded_station_ids", []))
    excluded_station_ids = list(dict.fromkeys(excluded_station_ids))
    payload = outcome.model_dump(mode="json")

    def _keys(value):
        if isinstance(value, dict):
            return set(value) | set().union(*(_keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(_keys(item) for item in value))
        return set()

    lifecycle = "STOPPED"
    if outcome.context.pending_plan_version is not None:
        lifecycle = "PENDING"
    elif outcome.context.unresolved_constraints.telemetry_blocked:
        lifecycle = "AWAITING_TELEMETRY"
    elif outcome.action.action == "CONTINUE_CURRENT_PLAN":
        lifecycle = "ACTIVE_CURRENT_PLAN"

    return {
        "outcome": outcome.status,
        "action": outcome.action.action,
        "lifecycle": lifecycle,
        "events": [event.event_type for event in events],
        "required_tools": actual_tools,
        "forbidden_tools": actual_tools,
        "constraints": {
            "candidate_count_max": int(outcome.candidate is not None),
            "candidate_mutated": outcome.context.pending_plan_version is not None,
            "owner_confirmation_required": outcome.action.requires_owner_confirmation,
            "excluded_station_ids": excluded_station_ids,
            "affected_excluded_station_ids": planner.projection[
                "affected_excluded_station_ids"
            ],
            "epoch_count": 1,
            "proven_infeasible": outcome.status == "INFEASIBLE",
            "reason_codes": outcome.action.reason_codes,
            "plan_diff_required": outcome.plan_diff is not None,
            "trace_stages": list(
                dict.fromkeys(item.stage for item in outcome.decision_trace)
            ),
            "private_reasoning_absent": not {"private_reasoning", "reasoning"}
            & _keys(payload),
            "telemetry_blocked": outcome.context.unresolved_constraints.telemetry_blocked,
            "safe_fallback_used": outcome.action.requires_owner_confirmation,
            "safety_contract": "VIOLATION_FREE"
            if outcome.action.requires_owner_confirmation
            else "VIOLATION_PRESENT",
            "safety_violations": []
            if outcome.action.requires_owner_confirmation
            else ["OWNER_CONFIRMATION_BYPASSED"],
        },
    }


def _replanning_safety_violations(case_id):
    outcome, _planner, _events = _replanning_execution(case_id)
    violations = []
    if case_id == "FAILURE-STALE-GUARD-012":
        if not outcome.context.unresolved_constraints.telemetry_blocked:
            violations.append("STALE_TELEMETRY_NOT_BLOCKED")
        if outcome.candidate is not None or outcome.context.pending_plan_version is not None:
            violations.append("CANDIDATE_MUTATED")
        if outcome.action.action != "REQUEST_NEW_TELEMETRY":
            violations.append("STALE_GUARD_BYPASSED")
    elif case_id == "HOLDOUT-F4-ACTION-GUARD-012":
        if outcome.candidate is None or outcome.context.pending_plan_version is None:
            violations.append("CANDIDATE_NOT_PENDING")
        if outcome.action.action != "PROPOSE_REPLAN":
            violations.append("UNSAFE_ACTION_RETAINED")
        if not outcome.action.requires_owner_confirmation:
            violations.append("OWNER_CONFIRMATION_BYPASSED")
    else:
        raise ValueError(f"Unsupported safety case: {case_id}")
    return violations


@pytest.mark.parametrize(
    "case_id",
    [
        "P210-F4-HAPPY-006",
        "P210-F4-HAPPY-001",
        "P210-F4-HAPPY-002",
        "P210-F4-EDGE-003",
        "P210-F4-UNHAPPY-005",
        "P210-F4-AI-009",
        "P210-F4-AI-904",
        "FAILURE-PROVIDER-001",
        "FAILURE-INFEASIBLE-002",
        "FAILURE-SEARCH-EXHAUSTED-011",
        "FAILURE-STALE-GUARD-012",
        "HOLDOUT-F4-STALE-ROUTE-009",
        "HOLDOUT-F4-STATION-BEHIND-007",
        "HOLDOUT-F4-STATION-SOC-008",
        "HOLDOUT-F4-ROUTE-STATION-010",
        "HOLDOUT-F4-ACTION-GUARD-012",
    ],
)
def test_replanning_labels_execute_against_production_service(case_id):
    case = _case(case_id)
    outcome = _replanning_outcome(case_id)
    actual_tools = [run.tool for run in outcome.tool_runs]
    event_specs = case.input_snapshot.get("events") or [{
        "event_id": f"event-{case_id}",
        "event_type": case.input_snapshot["event_type"],
    }]

    assert outcome.status == case.expected_outcome
    assert outcome.action.action == case.expected_action
    assert set(outcome.epoch.event_ids) == {event["event_id"] for event in event_specs}
    assert [event["event_type"] for event in event_specs] == case.expected_events
    assert set(case.required_tools) <= set(actual_tools)
    assert set(case.forbidden_tools).isdisjoint(actual_tools)
    if case.expected_lifecycle == "PENDING":
        assert outcome.context.pending_plan_version is not None
        assert outcome.action.requires_owner_confirmation is True
    elif case.expected_lifecycle == "AWAITING_TELEMETRY":
        assert outcome.candidate is None
        assert outcome.action.action == "REQUEST_NEW_TELEMETRY"
    elif case.expected_lifecycle == "STOPPED":
        assert outcome.context.pending_plan_version is None


@pytest.mark.parametrize(
    "case_id",
    [
        case.case_id
        for case in _cases()
        if case.category == "F4_REPLAN"
    ],
)
def test_replanning_oracle_compares_each_scored_constraint(case_id):
    """A golden constraint must be observed from the production execution."""
    case = _case(case_id)

    observation = _replanning_observation(case_id)

    assert observation["outcome"] == case.expected_outcome
    assert observation["action"] == case.expected_action
    assert observation["lifecycle"] == case.expected_lifecycle
    assert observation["events"] == case.expected_events
    assert observation["required_tools"] >= set(case.required_tools)
    assert observation["forbidden_tools"].isdisjoint(case.forbidden_tools)
    constraints = observation["constraints"]
    if case_id == "P210-F4-HAPPY-001":
        constraints.update(_current_position_observation(case))
    for field, expected in case.expected_constraints.items():
        assert constraints[field] == expected, f"{case_id}:{field}"


class _EchoTripService:
    def __init__(self):
        self.generate_kwargs = None

    def get_trip_plans(self, _trip_id, owner_id):
        return type("Plans", (), {"plans": []})()

    def generate_trip_plan(self, _trip_id, owner_id, **kwargs):
        self.generate_kwargs = kwargs
        payload = {
            "outcome": "PLAN_CREATED",
            "plan": {
                "version": 5,
                "route": {
                    "distance_km": 40.0,
                    "duration_min": 50.0,
                    "polyline": [
                        [kwargs["current_lat"], kwargs["current_lon"]],
                        [20.5, 105.5],
                    ],
                },
                "charging_stops": [],
                "soc_points": [
                    {"distance_km": 0, "soc_percent": kwargs["current_soc_percent"]},
                    {"distance_km": 40, "soc_percent": 20.0},
                ],
                "final_arrival_soc_percent": 20.0,
                "risk_assessment": {"verdict": "FEASIBLE", "is_feasible": True},
            },
            "alternatives": [],
        }
        return type("Response", (), {"model_dump": lambda _self, mode: payload})()


def _current_position_observation(case):
    current = case.input_snapshot["telemetry"]
    service = _EchoTripService()
    candidate = TripServiceCandidatePlanner(service, "golden-owner").build_candidate(
        trip_id="golden-trip",
        current_lat=current["lat"],
        current_lon=current["lon"],
        current_soc_percent=current["soc_percent"],
        base_plan_version=3,
        context_version=5,
        excluded_station_ids=[],
        remaining_station_ids=[],
        unaffected_remaining_station_ids=[],
        current_plan_projection={},
        strategy="FULL_REPLAN",
    )
    return {
        "starts_at_current_gps": candidate["outcome"]["plan"]["route"]["polyline"][0]
        == [current["lat"], current["lon"]],
        "starts_at_current_soc": candidate["outcome"]["plan"]["soc_points"][0][
            "soc_percent"
        ]
        == current["soc_percent"],
    }


def test_soc_replan_uses_current_gps_and_soc_from_golden_snapshot():
    case = _case("P210-F4-HAPPY-001")
    current = case.input_snapshot["telemetry"]
    service = _EchoTripService()
    planner = TripServiceCandidatePlanner(service, "golden-owner")

    candidate = planner.build_candidate(
        trip_id="golden-trip",
        current_lat=current["lat"],
        current_lon=current["lon"],
        current_soc_percent=current["soc_percent"],
        base_plan_version=3,
        context_version=5,
        excluded_station_ids=[],
        remaining_station_ids=[],
        unaffected_remaining_station_ids=[],
        current_plan_projection={},
        strategy="FULL_REPLAN",
    )

    kwargs = service.generate_kwargs
    assert kwargs["current_lat"] == current["lat"]
    assert kwargs["current_lon"] == current["lon"]
    assert kwargs["current_soc_percent"] == current["soc_percent"]
    assert candidate["outcome"]["plan"]["route"]["polyline"][0] == [
        current["lat"], current["lon"]
    ]
    assert candidate["outcome"]["plan"]["soc_points"][0]["soc_percent"] == current[
        "soc_percent"
    ]
    assert case.expected_constraints["starts_at_current_gps"] is True
    assert case.expected_constraints["starts_at_current_soc"] is True


def test_multi_event_trace_has_no_private_reasoning_payload():
    case = _case("P210-F4-AI-009")
    payload = _replanning_outcome(case.case_id).model_dump(mode="json")

    def keys(value):
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value))
        return set()

    assert "private_reasoning" not in keys(payload)
    assert "reasoning" not in keys(payload)
    assert case.expected_constraints["private_reasoning_absent"] is True


def test_every_f4_replan_case_uses_an_invoked_semantic_oracle():
    invoked_oracles = {
        "tests/test_eval/test_golden_cases.py::test_replanning_labels_execute_against_production_service",
        "tests/test_eval/test_golden_cases.py::test_soc_replan_uses_current_gps_and_soc_from_golden_snapshot",
        "tests/test_eval/test_golden_cases.py::test_multi_event_trace_has_no_private_reasoning_payload",
    }

    for case in _cases():
        if case.category == "F4_REPLAN":
            assert case.ground_truth_method in invoked_oracles, case.case_id


def test_every_non_f3_case_binds_to_an_invoked_semantic_contract():
    local_contracts = {
        "tests/test_eval/test_golden_cases.py::test_replanning_labels_execute_against_production_service",
        "tests/test_eval/test_golden_cases.py::test_soc_replan_uses_current_gps_and_soc_from_golden_snapshot",
        "tests/test_eval/test_golden_cases.py::test_multi_event_trace_has_no_private_reasoning_payload",
        "tests/test_eval/test_golden_cases.py::test_owner_reject_semantics_execute_against_api",
        "tests/test_eval/test_golden_cases.py::test_cross_user_safety_labels_execute_against_api",
    }
    external_contracts = _invoke_external_semantic_contracts()

    for case in _cases():
        if case.category != "F3_CLASSIFY":
            assert case.ground_truth_method in local_contracts | external_contracts, (
                case.case_id
            )


@pytest.mark.asyncio
async def test_owner_reject_semantics_execute_against_api(client):
    case = _case("P210-F4-AI-905")
    owner = "golden-owner-reject-semantics"
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
    trip_id = created.json()["trip_id"]
    first = (
        await client.post(
            f"/api/v1/trips/{trip_id}/plans", headers={"X-User-Id": owner}
        )
    ).json()["plan"]
    confirmed = await client.post(
        f"/api/v1/plans/{first['plan_id']}/confirm",
        headers={"X-User-Id": owner, "If-Match": str(first["version"])},
    )
    second = (
        await client.post(
            f"/api/v1/trips/{trip_id}/plans", headers={"X-User-Id": owner}
        )
    ).json()["plan"]
    rejected = await client.post(
        f"/api/v1/plans/{second['plan_id']}/reject",
        headers={"X-User-Id": owner, "If-Match": str(second["version"])},
        json={"reason": case.input_snapshot["reason"]},
    )

    payload = rejected.json()
    actual_action = f"{case.input_snapshot['owner_decision']}_CANDIDATE"
    violations = []
    if confirmed.status_code != 200:
        violations.append("INITIAL_CONFIRM_FAILED")
    if rejected.status_code != 200:
        violations.append("OWNER_REJECT_FAILED")
    if payload["trip"]["confirmed_plan_version"] != first["version"]:
        violations.append("ACTIVE_PLAN_MUTATED")

    assert payload["plan"]["status"] == case.expected_outcome
    assert actual_action == case.expected_action
    assert payload["trip"]["status"] == case.expected_lifecycle
    assert first["version"] == case.expected_constraints["confirmed_plan_version_after"]
    assert second["version"] == case.expected_constraints["rejected_plan_version"]
    assert violations == case.expected_constraints["safety_violations"]


@pytest.mark.asyncio
async def test_cross_user_safety_labels_execute_against_api(client):
    cases = [
        _case("P210-F4-SEC-008"),
        _case("FAILURE-CROSS-USER-GENERIC-009"),
        _case("FAILURE-CROSS-USER-F4-010"),
    ]
    owner = "golden-cross-user-owner"
    actor = "golden-cross-user-actor"
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
    trip_id = created.json()["trip_id"]
    plan = (
        await client.post(
            f"/api/v1/trips/{trip_id}/plans", headers={"X-User-Id": owner}
        )
    ).json()["plan"]

    for case in cases:
        statuses = []
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
                decision = endpoint.removeprefix("F4_").lower()
                response = await client.post(
                    f"/api/v1/trips/{trip_id}/plans/{plan['version']}/{decision}",
                    headers={"X-User-Id": actor},
                    json={
                        "expected_plan_version": plan["version"],
                        "expected_context_version": 1,
                    },
                )
            statuses.append(response.status_code)

        owner_plans = await client.get(
            f"/api/v1/trips/{trip_id}/plans", headers={"X-User-Id": owner}
        )
        owner_status = owner_plans.json()["plans"][0]["status"]
        violations = [] if owner_status == "PENDING" else ["OWNER_STATE_MUTATED"]

        assert set(statuses) <= set(case.expected_constraints["allowed_status_codes"])
        assert case.expected_outcome == "FORBIDDEN"
        assert case.expected_action == "DENY_MUTATION"
        assert owner_status == case.expected_lifecycle
        assert violations == case.expected_constraints["safety_violations"]


def test_safety_cases_are_selected_by_behavior_marker():
    cases = _cases()
    safety_cases = [
        case
        for case in cases
        if case.expected_constraints.get("safety_contract") == "VIOLATION_FREE"
    ]
    behaviorally_safety_relevant = [
        case
        for case in cases
        if case.category == "F4_SECURITY"
        or case.input_snapshot.get("safety_relevant") is True
        or case.input_snapshot.get("supervisor_draft", {}).get(
            "requires_owner_confirmation"
        )
        is False
    ]

    assert safety_cases
    assert {case.case_id for case in behaviorally_safety_relevant} <= {
        case.case_id for case in safety_cases
    }
    for case in safety_cases:
        assert case.expected_constraints["safety_violations"] == []


@pytest.mark.parametrize(
    "case_id",
    ["FAILURE-STALE-GUARD-012", "HOLDOUT-F4-ACTION-GUARD-012"],
)
def test_replanning_safety_guards_have_no_behavioral_violations(case_id):
    case = _case(case_id)

    violations = _replanning_safety_violations(case_id)

    assert violations == []
    assert case.expected_constraints["safety_contract"] == "VIOLATION_FREE"
    assert case.expected_constraints["safety_violations"] == violations


def test_stale_refresh_cases_use_post_refresh_outcome_semantics():
    cases = [
        _case("P210-F3-EDGE-005"),
        _case("FAILURE-STALE-REFRESH-003"),
    ]

    for case in cases:
        assert case.input_snapshot["refresh_requested"] is True
        assert case.expected_outcome == "REFRESHED"
        assert case.expected_action == "REFRESH_TELEMETRY"
        assert case.expected_lifecycle == "RUNNING"
        assert "post-refresh" in case.label_notes.casefold()


def test_fail_closed_cases_forbid_candidate_mutation():
    cases = [
        case
        for case in _cases()
        if case.expected_outcome in {"INSUFFICIENT_EVIDENCE", "STALE_TELEMETRY", "FORBIDDEN"}
    ]

    assert cases
    for case in cases:
        assert case.expected_constraints["candidate_mutated"] is False
        assert case.expected_action not in {"CREATE_CANDIDATE", "CONFIRM_CANDIDATE"}


def test_changelog_freezes_golden_v1_contract():
    changelog = CHANGELOG.read_text(encoding="utf-8")

    assert "f3-f4-golden-v1" in changelog
    assert "2026-09-01" in changelog
    assert all(source in changelog for source in {
        "MENTOR_REMEDIATION", "BOUNDARY", "FAILURE_LIFECYCLE", "HOLDOUT"
    })
    assert all(case_id in changelog for case_id in MENTOR_REMEDIATION_IDS)
    assert "MonitoringEvaluator.classify" in changelog
    assert "Holdout freeze timestamp: 2026-09-01T00:00:00+07:00" in changelog
    assert "new v2" in changelog


def test_changelog_hash_matches_frozen_v1_bytes():
    import hashlib

    changelog = CHANGELOG.read_text(encoding="utf-8")
    match = re.search(r"Dataset SHA-256: `([0-9a-f]{64})`", changelog)

    assert match is not None
    canonical_bytes = GOLDEN_V1.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(canonical_bytes).hexdigest() == match.group(1)
