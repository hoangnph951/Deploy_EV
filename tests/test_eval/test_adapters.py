from __future__ import annotations

from pathlib import Path

import pytest

from eval.adapters import adapter_for, run_accuracy_cases, sanitize_raw_contract
from eval.contracts import GoldenCase
from eval.dataset import load_golden_cases
from eval.local_app import create_evaluation_harness
from src.packages.agent.replanning.openai_adapter import OpenAISupervisor


class _UnusedResponses:
    def parse(self, **_kwargs):
        raise AssertionError("Live supervisor construction must not call the network")


class _UnusedOpenAIClient:
    def __init__(self):
        self.responses = _UnusedResponses()


def _case(case_id: str, category: str, input_snapshot: dict) -> GoldenCase:
    return GoldenCase(
        case_id=case_id,
        source="FAILURE_LIFECYCLE",
        category=category,
        input_snapshot=input_snapshot,
        expected_events=[],
        expected_constraints={},
        required_tools=[],
        forbidden_tools=[],
        expected_outcome="",
        expected_action=None,
        expected_lifecycle=None,
        ground_truth_method="executable-test",
        label_notes="Adapter fixture.",
        dataset_version="f3-f4-golden-v1",
    )


@pytest.fixture
def harness(tmp_path: Path):
    return create_evaluation_harness(
        tmp_path / "evaluation.db",
        supervisor_mode="fallback",
    )


@pytest.mark.asyncio
async def test_f3_classify_adapter_uses_strict_boundary(harness):
    equal = _case(
        "boundary-equal",
        "F3_CLASSIFY",
        {
            "off_route_distance_km": 2.0,
            "soc_deficit_percent": 5.0,
            "silent_seconds": 60,
            "station_unavailable": False,
        },
    )
    above = _case(
        "boundary-above",
        "F3_CLASSIFY",
        {
            "off_route_distance_km": 2.01,
            "soc_deficit_percent": 5.0,
            "silent_seconds": 60,
            "station_unavailable": False,
        },
    )

    predictions = await run_accuracy_cases([equal, above], harness)

    assert [item.outcome for item in predictions] == ["NORMAL", "ROUTE_DEVIATION"]
    assert predictions[0].events == []
    assert predictions[1].events == ["ROUTE_DEVIATION"]
    assert all(item.supervisor_mode == "DETERMINISTIC_ORACLE" for item in predictions)


@pytest.mark.asyncio
async def test_f4_provider_failure_adapter_returns_typed_insufficient_evidence(harness):
    case = _case(
        "provider-failure",
        "F4_REPLAN",
        {
            "fault": "F1_PROVIDER_FAILURE",
            "event_type": "ROUTE_DEVIATION",
            "telemetry_snapshot_id": "provider-failure-snapshot",
        },
    )

    prediction = await adapter_for(case, harness).execute(case)

    assert prediction.outcome == "INSUFFICIENT_EVIDENCE"
    assert prediction.action == "STOP_INSUFFICIENT_EVIDENCE"
    assert prediction.candidate_count == 0
    assert prediction.constraints["candidate_mutated"] is False
    assert prediction.safety_violations == []
    assert "build_full_replan" in prediction.selected_tools


@pytest.mark.asyncio
async def test_security_adapter_detects_any_cross_user_mutation(harness):
    case = _case(
        "cross-user",
        "F4_SECURITY",
        {
            "endpoint_set": ["F2_CONFIRM", "F2_REJECT", "F4_CONFIRM", "F4_REJECT"],
        },
    )

    prediction = await adapter_for(case, harness).execute(case)

    assert prediction.outcome == "FORBIDDEN"
    assert prediction.action == "DENY_MUTATION"
    assert prediction.lifecycle == "PENDING"
    assert set(prediction.constraints["http_statuses"]) <= {403, 404}
    assert prediction.safety_violations == []


def test_adapter_sanitizes_dynamic_ids_from_raw_contract():
    sanitized = sanitize_raw_contract(
        {
            "trip_id": "trip-secret",
            "agent_run_id": "run-secret",
            "telemetry": {"lat": 21.031, "lon": 105.812, "snapshot_id": "snap-secret"},
            "headers": {"Authorization": "Bearer secret", "X-User-Id": "owner"},
            "provider_payload": {"free_form": "untrusted response"},
            "station_id": "ST-10",
            "status": "SUCCEEDED",
        }
    )

    assert sanitized == {
        "trip_id": "[SANITIZED_ID]",
        "agent_run_id": "[SANITIZED_ID]",
        "telemetry": {"snapshot_id": "[SANITIZED_ID]"},
        "station_id": "ST-10",
        "status": "SUCCEEDED",
    }


def test_evaluation_app_keeps_deterministic_tools_but_allows_live_supervisor(tmp_path):
    supplied = OpenAISupervisor(
        api_key="evaluation-test-key",
        model="evaluation-test-model",
        client=_UnusedOpenAIClient(),
    )

    harness = create_evaluation_harness(
        tmp_path / "live-evaluation.db",
        supervisor_mode="live",
        supervisor=supplied,
    )

    assert harness.supervisor is supplied
    assert harness.provider_modes == {
        "routing": "fixture",
        "station": "fixture",
        "environment": "fixture",
        "supervisor": "live",
    }
    assert harness.app.dependency_overrides


@pytest.mark.asyncio
async def test_timeout_mode_uses_production_fallback_path(tmp_path):
    harness = create_evaluation_harness(
        tmp_path / "timeout-evaluation.db",
        supervisor_mode="timeout",
    )
    case = _case(
        "timeout-fallback",
        "F4_REPLAN",
        {
            "fault": "F1_PROVIDER_FAILURE",
            "event_type": "ROUTE_DEVIATION",
        },
    )

    prediction = await adapter_for(case, harness).execute(case)

    assert prediction.outcome == "INSUFFICIENT_EVIDENCE"
    assert prediction.supervisor_mode == "SAFE_FALLBACK"
    assert prediction.model is None


@pytest.mark.asyncio
async def test_adapters_execute_every_golden_case(tmp_path):
    cases = load_golden_cases(Path("eval/datasets/f3_f4_golden_v1.jsonl"))
    harness = create_evaluation_harness(
        tmp_path / "all-golden-cases.db",
        supervisor_mode="fallback",
    )

    predictions = await run_accuracy_cases(cases, harness)

    assert len(predictions) == len(cases) == 60
    assert {prediction.case_id for prediction in predictions} == {
        case.case_id for case in cases
    }
