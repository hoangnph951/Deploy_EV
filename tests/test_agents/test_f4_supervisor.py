import json

from src.packages.agent.replanning.fallback import ConservativeSupervisor
from src.packages.agent.replanning.openai_adapter import OpenAISupervisor
from src.packages.agent.replanning.schemas import DiagnosticObservation, ReflectionDecision
from src.packages.contracts.replanning import ActiveConstraintContext


def test_fallback_requests_telemetry_when_safety_evidence_is_stale() -> None:
    turn = ConservativeSupervisor().assess(
        event_types=["STALE_TELEMETRY", "SOC_UNDERPERFORMANCE"],
        active_constraints=ActiveConstraintContext(telemetry_blocked=True),
    )
    assert turn.assessment.primary_objective == "RECOVER_TELEMETRY"
    assert turn.decision.decision == "PROPOSE_ACTION"
    assert turn.action.action == "REQUEST_NEW_TELEMETRY"


def test_fallback_builds_composite_candidate_with_blacklist() -> None:
    turn = ConservativeSupervisor().assess(
        event_types=["SOC_UNDERPERFORMANCE", "STATION_UNAVAILABLE"],
        active_constraints=ActiveConstraintContext(
            soc_underperformance_active=True, excluded_station_ids=["ST-10"]
        ),
    )
    assert turn.assessment.primary_objective == "COMPOSITE_RECOVERY"
    assert turn.decision.tool_name == "build_candidate"
    assert turn.decision.arguments["excluded_station_ids"] == ["ST-10"]


def test_openai_adapter_retries_invalid_output_once_then_falls_back() -> None:
    class InvalidResponses:
        def __init__(self):
            self.calls = 0

        def parse(self, **kwargs):
            self.calls += 1
            raise ValueError("invalid structured output")

    class FakeClient:
        def __init__(self):
            self.responses = InvalidResponses()

    client = FakeClient()
    supervisor = OpenAISupervisor(api_key="test", model="test-model", client=client)
    turn = supervisor.assess(
        event_types=["STALE_TELEMETRY"],
        active_constraints=ActiveConstraintContext(telemetry_blocked=True),
    )
    assert client.responses.calls == 2
    assert turn.action.action == "REQUEST_NEW_TELEMETRY"


def test_openai_adapter_reflection_retries_once_then_uses_safe_fallback() -> None:
    class InvalidResponses:
        def __init__(self):
            self.calls = 0

        def parse(self, **kwargs):
            self.calls += 1
            raise ValueError("invalid reflection")

    class FakeClient:
        def __init__(self):
            self.responses = InvalidResponses()

    client = FakeClient()
    supervisor = OpenAISupervisor(api_key="test", model="test-model", client=client)
    reflection = supervisor.reflect(
        event_types=["SOC_UNDERPERFORMANCE"],
        active_constraints=ActiveConstraintContext(soc_underperformance_active=True),
        observations=[DiagnosticObservation(
            tool="inspect_telemetry", status="SUCCEEDED", provider="F3_TELEMETRY",
            freshness="FRESH", evidence_refs=["telemetry:1"],
            reason_codes=["TELEMETRY_VERIFIED"],
        )],
        allowed_tools=["project_current_plan"],
    )

    assert client.responses.calls == 2
    assert reflection.next_step == "CALL_TOOL"
    assert reflection.next_tool == "project_current_plan"


def test_openai_adapter_drafts_action_without_private_reasoning_payload() -> None:
    class CapturingResponses:
        def __init__(self):
            self.inputs = []

        def parse(self, **kwargs):
            self.inputs.append(kwargs["input"])
            return type("Response", (), {"output_parsed": None})()

    class FakeClient:
        def __init__(self):
            self.responses = CapturingResponses()

    client = FakeClient()
    supervisor = OpenAISupervisor(api_key="test", model="test-model", client=client)
    action = supervisor.draft_action(
        feasibility_verdict="FEASIBLE",
        observations=[],
        plan_diff=None,
    )

    assert action.action == "PROPOSE_REPLAN"
    user_payloads = client.responses.inputs
    assert all("reasoning" not in payload.lower() for payload in user_payloads)


def test_openai_reflection_receives_full_operational_context_and_system_instructions() -> None:
    class CapturingResponses:
        def __init__(self):
            self.calls = []

        def parse(self, **kwargs):
            self.calls.append(kwargs)
            return type("Response", (), {"output_parsed": ReflectionDecision(
                evidence_sufficient=False,
                hypothesis_status="UNCERTAIN",
                next_step="CALL_TOOL",
                next_tool="nearest_station_reachability",
                public_summary="SOC dự phòng có rủi ro; cần kiểm tra trạm gần nhất.",
            )})()

    class FakeClient:
        def __init__(self):
            self.responses = CapturingResponses()

    client = FakeClient()
    supervisor = OpenAISupervisor(api_key="test", model="test-model", client=client)
    reflection = supervisor.reflect(
        event_types=["SOC_UNDERPERFORMANCE"],
        active_constraints=ActiveConstraintContext(soc_underperformance_active=True),
        observations=[DiagnosticObservation(
            tool="inspect_energy", status="SUCCEEDED", provider="F1_ENERGY_MODEL",
            freshness="FRESH", facts={"soc_percent": 40, "expected_soc_percent": 48},
            evidence_refs=["telemetry:5"], public_summary="SOC thấp hơn kỳ vọng.",
        )],
        allowed_tools=["nearest_station_reachability"],
        context={"trip_id": "trip-1", "current_confirmed_plan_version": 3},
        telemetry={"lat": 20.9, "lon": 105.1, "soc_percent": 40},
        assessment={"primary_objective": "PROTECT_RESERVE_SOC"},
    )

    call = client.responses.calls[0]
    payload = json.loads(call["input"])
    assert "SOC_UNDERPERFORMANCE POLICY" in call["instructions"]
    assert "STATION_UNAVAILABLE POLICY" in call["instructions"]
    assert payload["trip_context"]["trip_id"] == "trip-1"
    assert payload["telemetry"]["soc_percent"] == 40
    assert payload["assessment"]["primary_objective"] == "PROTECT_RESERVE_SOC"
    assert payload["allowed_tools"] == ["nearest_station_reachability"]
    assert reflection.next_tool == "nearest_station_reachability"


def test_openai_supervisor_uses_safe_fallback_after_llm_turn_budget() -> None:
    class CountingResponses:
        def __init__(self):
            self.calls = 0

        def parse(self, **kwargs):
            self.calls += 1
            raise ValueError("invalid output")

    class FakeClient:
        def __init__(self):
            self.responses = CountingResponses()

    client = FakeClient()
    supervisor = OpenAISupervisor(
        api_key="test", model="test-model", client=client, max_turns=1,
    )
    turn = supervisor.assess(
        event_types=["SOC_UNDERPERFORMANCE"],
        active_constraints=ActiveConstraintContext(soc_underperformance_active=True),
    )

    assert client.responses.calls == 1
    assert turn.assessment.primary_objective == "PROTECT_RESERVE_SOC"


def test_openai_assessment_receives_the_runtime_tool_allowlist() -> None:
    class CapturingResponses:
        def __init__(self):
            self.inputs = []

        def parse(self, **kwargs):
            self.inputs.append(json.loads(kwargs["input"]))
            raise ValueError("force safe fallback")

    class FakeClient:
        def __init__(self):
            self.responses = CapturingResponses()

    client = FakeClient()
    supervisor = OpenAISupervisor(api_key="test", model="test-model", client=client)
    supervisor.assess(
        event_types=["ROUTE_DEVIATION", "STATION_UNAVAILABLE"],
        active_constraints=ActiveConstraintContext(excluded_station_ids=["ST-10"]),
        allowed_tools=[
            "inspect_telemetry", "project_current_plan", "inspect_route", "inspect_stations",
        ],
    )

    assert client.responses.inputs[0]["allowed_tools"] == [
        "inspect_telemetry", "project_current_plan", "inspect_route", "inspect_stations",
    ]
