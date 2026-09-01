import json
import logging

from src.packages.agent.replanning.fallback import ConservativeSupervisor
from src.packages.agent.replanning.openai_adapter import OpenAISupervisor
from src.packages.agent.replanning.schemas import (
    DiagnosticObservation,
    ReflectionDecision,
    SituationAssessment,
    SupervisorStructuredTurn,
    ToolDecision,
)
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
            tool="project_current_plan", status="SUCCEEDED", provider="F2_PLAN_HISTORY",
            freshness="FRESH", evidence_refs=["plan:1"],
            reason_codes=["CURRENT_PLAN_PROJECTED"],
        )],
        allowed_tools=["project_current_plan"],
    )

    assert client.responses.calls == 2
    assert reflection.next_step == "CALL_TOOL"
    assert reflection.next_tool == "project_current_plan"
    assert reflection.response_source == "SAFE_FALLBACK"


def test_openai_adapter_retries_assessment_that_selects_no_allowed_tool() -> None:
    assessment = SituationAssessment(
        primary_objective="COMPOSITE_RECOVERY",
        urgency="HIGH",
        strategy="Collect event-specific evidence.",
        confidence=0.8,
    )

    class RepairableResponses:
        def __init__(self):
            self.calls = 0

        def parse(self, **kwargs):
            self.calls += 1
            decision = (
                ToolDecision(decision="STOP")
                if self.calls == 1
                else ToolDecision(decision="CALL_TOOL", tool_name="inspect_route")
            )
            return type("Response", (), {"output_parsed": SupervisorStructuredTurn(
                assessment=assessment,
                decision=decision,
            )})()

    responses = RepairableResponses()
    supervisor = OpenAISupervisor(
        api_key="test",
        model="test-model",
        client=type("Client", (), {"responses": responses})(),
    )

    turn = supervisor.assess(
        event_types=["ROUTE_DEVIATION", "SOC_UNDERPERFORMANCE"],
        active_constraints=ActiveConstraintContext(),
        allowed_tools=["project_current_plan", "inspect_route", "inspect_energy"],
    )

    assert responses.calls == 2
    assert turn.decision.decision == "CALL_TOOL"
    assert turn.decision.tool_name == "inspect_route"


def test_openai_adapter_retries_reflection_that_stops_before_allowed_tool() -> None:
    class RepairableResponses:
        def __init__(self):
            self.calls = 0

        def parse(self, **kwargs):
            self.calls += 1
            reflection = ReflectionDecision(
                evidence_sufficient=False,
                hypothesis_status="UNCERTAIN",
                next_step=(
                    "STOP_INSUFFICIENT_EVIDENCE" if self.calls == 1 else "CALL_TOOL"
                ),
                next_tool="inspect_energy",
            )
            return type("Response", (), {"output_parsed": reflection})()

    responses = RepairableResponses()
    supervisor = OpenAISupervisor(
        api_key="test",
        model="test-model",
        client=type("Client", (), {"responses": responses})(),
    )

    reflection = supervisor.reflect(
        event_types=["SOC_UNDERPERFORMANCE"],
        active_constraints=ActiveConstraintContext(soc_underperformance_active=True),
        observations=[],
        allowed_tools=["inspect_energy", "nearest_station_reachability"],
    )

    assert responses.calls == 2
    assert reflection.next_step == "CALL_TOOL"
    assert reflection.next_tool == "inspect_energy"


def test_openai_adapter_retry_includes_schema_correction() -> None:
    class RepairableResponses:
        def __init__(self):
            self.calls = []

        def parse(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return ReflectionDecision.model_validate({
                    "primary_objective": "PRIVATE_SENTINEL",
                    "decision": "REQUEST_NEXT_TOOL",
                })
            return type("Response", (), {"output_parsed": ReflectionDecision(
                evidence_sufficient=False,
                hypothesis_status="UNCERTAIN",
                next_step="CALL_TOOL",
                next_tool="project_current_plan",
                public_summary="Cáº§n chiáº¿u pháº§n hÃ nh trÃ¬nh cÃ²n láº¡i.",
            )})()

    responses = RepairableResponses()
    client = type("Client", (), {"responses": responses})()
    supervisor = OpenAISupervisor(api_key="test", model="test-model", client=client)

    reflection = supervisor.reflect(
        event_types=["SOC_UNDERPERFORMANCE"],
        active_constraints=ActiveConstraintContext(soc_underperformance_active=True),
        observations=[],
        allowed_tools=["project_current_plan"],
    )

    first_payload = json.loads(responses.calls[0]["input"])
    retry_payload = json.loads(responses.calls[1]["input"])
    assert first_payload["output_contract"]["schema"] == "ReflectionDecision"
    assert "schema_correction" not in first_payload
    assert retry_payload["schema_correction"]["attempt"] == 2
    assert "evidence_sufficient: Field required" in retry_payload["schema_correction"]["previous_error"]
    assert "PRIVATE_SENTINEL" not in json.dumps(retry_payload)
    assert "REFLECT OUTPUT CONTRACT" in responses.calls[1]["instructions"]
    assert reflection.response_source == "OPENAI"


def test_openai_adapter_opens_circuit_after_repeated_schema_failure() -> None:
    class InvalidResponses:
        def __init__(self):
            self.calls = 0

        def parse(self, **kwargs):
            self.calls += 1
            raise ValueError("provider ignored structured schema")

    responses = InvalidResponses()
    client = type("Client", (), {"responses": responses})()
    supervisor = OpenAISupervisor(api_key="test", model="test-model", client=client)

    supervisor.assess(
        event_types=["SOC_UNDERPERFORMANCE"],
        active_constraints=ActiveConstraintContext(soc_underperformance_active=True),
        allowed_tools=["project_current_plan"],
    )
    reflection = supervisor.reflect(
        event_types=["SOC_UNDERPERFORMANCE"],
        active_constraints=ActiveConstraintContext(soc_underperformance_active=True),
        observations=[],
        allowed_tools=["project_current_plan"],
    )

    assert responses.calls == 2
    assert reflection.response_source == "SAFE_FALLBACK"


def test_openai_adapter_marks_successful_reflection_as_openai() -> None:
    class SuccessfulResponses:
        def parse(self, **kwargs):
            return type("Response", (), {"output_parsed": ReflectionDecision(
                evidence_sufficient=False,
                hypothesis_status="UNCERTAIN",
                next_step="CALL_TOOL",
                next_tool="project_current_plan",
                public_summary="GPT đánh giá telemetry và chọn kiểm tra hành trình còn lại.",
            )})()

    client = type("Client", (), {"responses": SuccessfulResponses()})()
    supervisor = OpenAISupervisor(api_key="test", model="test-model", client=client)

    reflection = supervisor.reflect(
        event_types=["SOC_UNDERPERFORMANCE"],
        active_constraints=ActiveConstraintContext(soc_underperformance_active=True),
        observations=[],
        allowed_tools=["project_current_plan"],
    )

    assert reflection.response_source == "OPENAI"


def test_openai_adapter_logs_fallback_reason(caplog) -> None:
    class InvalidResponses:
        def parse(self, **kwargs):
            raise ValueError("PRIVATE_SENTINEL")

    client = type("Client", (), {"responses": InvalidResponses()})()
    supervisor = OpenAISupervisor(api_key="test", model="test-model", client=client)

    with caplog.at_level(logging.WARNING):
        supervisor.reflect(
            event_types=["SOC_UNDERPERFORMANCE"],
            active_constraints=ActiveConstraintContext(soc_underperformance_active=True),
            observations=[],
            allowed_tools=["inspect_energy"],
        )

    assert "REFLECT" in caplog.text
    assert "ValueError" in caplog.text
    assert "PRIVATE_SENTINEL" not in caplog.text


def test_openai_adapter_logs_returned_keys_for_schema_mismatch(caplog) -> None:
    class WrongShapeResponses:
        def parse(self, **kwargs):
            return ReflectionDecision.model_validate({
                "primary_objective": "PROTECT_RESERVE_SOC",
                "decision": "REQUEST_NEXT_TOOL",
                "user_message": "PRIVATE_SENTINEL",
            })

    client = type("Client", (), {"responses": WrongShapeResponses()})()
    supervisor = OpenAISupervisor(api_key="test", model="test-model", client=client)

    with caplog.at_level(logging.WARNING):
        supervisor.reflect(
            event_types=["SOC_UNDERPERFORMANCE"],
            active_constraints=ActiveConstraintContext(soc_underperformance_active=True),
            observations=[],
            allowed_tools=["inspect_energy"],
        )

    assert "returned_keys=['decision', 'primary_objective', 'user_message']" in caplog.text
    assert "PRIVATE_SENTINEL" not in caplog.text


def test_openai_adapter_bounds_returned_key_diagnostics(caplog) -> None:
    oversized_key = "S" * 100
    wrong_shape = {f"key_{index:02d}": index for index in range(25)}
    wrong_shape[oversized_key] = "hidden"

    class WrongShapeResponses:
        def parse(self, **kwargs):
            return ReflectionDecision.model_validate(wrong_shape)

    client = type("Client", (), {"responses": WrongShapeResponses()})()
    supervisor = OpenAISupervisor(api_key="test", model="test-model", client=client)

    with caplog.at_level(logging.WARNING):
        supervisor.reflect(
            event_types=["SOC_UNDERPERFORMANCE"],
            active_constraints=ActiveConstraintContext(soc_underperformance_active=True),
            observations=[],
            allowed_tools=["inspect_energy"],
        )

    assert oversized_key not in caplog.text
    assert "key_24" not in caplog.text


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


def test_openai_supervisor_default_budget_covers_nine_successful_operations() -> None:
    class SuccessfulResponses:
        def __init__(self):
            self.calls = 0

        def parse(self, **kwargs):
            self.calls += 1
            return type("Response", (), {"output_parsed": ReflectionDecision(
                evidence_sufficient=False,
                hypothesis_status="UNCERTAIN",
                next_step="CALL_TOOL",
                next_tool="inspect_energy",
                public_summary=f"Phản ánh GPT số {self.calls}.",
            )})()

    responses = SuccessfulResponses()
    client = type("Client", (), {"responses": responses})()
    supervisor = OpenAISupervisor(api_key="test", model="test-model", client=client)

    reflections = [
        supervisor.reflect(
            event_types=["SOC_UNDERPERFORMANCE"],
            active_constraints=ActiveConstraintContext(soc_underperformance_active=True),
            observations=[],
            allowed_tools=["inspect_energy"],
        )
        for _ in range(9)
    ]

    assert responses.calls == 9
    assert [item.public_summary for item in reflections] == [
        f"Phản ánh GPT số {index}." for index in range(1, 10)
    ]


def test_default_budget_covers_full_flow_with_six_semantic_retries() -> None:
    class RepairingResponses:
        def __init__(self):
            self.calls = 0

        def parse(self, **kwargs):
            self.calls += 1
            if self.calls <= 12 and self.calls % 2 == 1:
                raise ValueError("retry this operation")
            return type("Response", (), {"output_parsed": ReflectionDecision(
                evidence_sufficient=False,
                hypothesis_status="UNCERTAIN",
                next_step="CALL_TOOL",
                next_tool="project_current_plan",
                public_summary=f"GPT operation {self.calls}.",
            )})()

    responses = RepairingResponses()
    supervisor = OpenAISupervisor(
        api_key="test",
        model="test-model",
        client=type("Client", (), {"responses": responses})(),
    )

    reflections = [
        supervisor.reflect(
            event_types=["ROUTE_DEVIATION"],
            active_constraints=ActiveConstraintContext(route_deviation_active=True),
            observations=[],
            allowed_tools=["project_current_plan"],
        )
        for _ in range(10)
    ]

    assert responses.calls == 16
    assert all(item.response_source == "OPENAI" for item in reflections)


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
            "project_current_plan", "inspect_route", "inspect_stations",
        ],
    )

    assert client.responses.inputs[0]["allowed_tools"] == [
        "project_current_plan", "inspect_route", "inspect_stations",
    ]
