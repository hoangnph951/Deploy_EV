from src.packages.agent.replanning.fallback import ConservativeSupervisor, SupervisorTurn
from src.packages.agent.replanning.schemas import ReflectionDecision, ToolDecision
from src.packages.core.replanning.application.service import ReplanningService
from tests.test_core.test_f4_replanning_service import (
    RecordingPlanner,
    context,
    event,
    telemetry,
)


class ModelOrderedSupervisor(ConservativeSupervisor):
    def assess(self, **kwargs) -> SupervisorTurn:
        turn = super().assess(**kwargs)
        allowed_tools = kwargs["allowed_tools"]
        return SupervisorTurn(
            assessment=turn.assessment,
            decision=ToolDecision(
                decision="CALL_TOOL",
                tool_name=(
                    "inspect_stations"
                    if "inspect_stations" in allowed_tools else allowed_tools[0]
                ),
                public_summary="Kiểm tra telemetry trước.",
            ),
            action=turn.action,
        )

    def reflect(self, *, allowed_tools, **kwargs) -> ReflectionDecision:
        if not allowed_tools:
            return ReflectionDecision(
                evidence_sufficient=True,
                hypothesis_status="SUPPORTED",
                next_step="PROPOSE_ACTION",
                response_source="OPENAI",
                public_summary="Đã đủ bằng chứng.",
            )
        preferred_order = [
            "inspect_stations",
            "project_current_plan",
            "inspect_route",
            "build_minimal_substitution",
            "build_full_replan",
            "compare_plans",
        ]
        selected = next(tool for tool in preferred_order if tool in allowed_tools)
        return ReflectionDecision(
            evidence_sufficient=False,
            hypothesis_status="UNCERTAIN",
            next_step="CALL_TOOL",
            next_tool=selected,
            response_source="OPENAI",
            public_summary=f"Chọn {selected} từ allowlist.",
        )


class InvalidToolSupervisor(ModelOrderedSupervisor):
    def assess(self, **kwargs) -> SupervisorTurn:
        turn = super().assess(**kwargs)
        return SupervisorTurn(
            assessment=turn.assessment,
            decision=ToolDecision(decision="CALL_TOOL", tool_name="unknown_tool"),
            action=turn.action,
        )


class RecordingAllowlistSupervisor(ConservativeSupervisor):
    def __init__(self):
        self.allowed_tool_history = []

    def assess(self, **kwargs) -> SupervisorTurn:
        allowed_tools = kwargs["allowed_tools"]
        self.allowed_tool_history.append(list(allowed_tools))
        turn = super().assess(**kwargs)
        return SupervisorTurn(
            assessment=turn.assessment,
            decision=ToolDecision(
                decision="CALL_TOOL",
                tool_name=allowed_tools[0],
            ),
            action=turn.action,
        )

    def reflect(self, *, allowed_tools, **kwargs) -> ReflectionDecision:
        self.allowed_tool_history.append(list(allowed_tools))
        if not allowed_tools:
            return ReflectionDecision(
                evidence_sufficient=True,
                hypothesis_status="SUPPORTED",
                next_step="PROPOSE_ACTION",
                response_source="OPENAI",
            )
        return ReflectionDecision(
            evidence_sufficient=False,
            hypothesis_status="UNCERTAIN",
            next_step="CALL_TOOL",
            next_tool=allowed_tools[0],
            response_source="OPENAI",
        )


class OutOfOrderInitialSupervisor(RecordingAllowlistSupervisor):
    def assess(self, **kwargs) -> SupervisorTurn:
        turn = super().assess(**kwargs)
        return SupervisorTurn(
            assessment=turn.assessment,
            decision=ToolDecision(
                decision="CALL_TOOL",
                tool_name="inspect_route",
            ),
            action=turn.action,
        )


class OutOfOrderReflectionSupervisor(RecordingAllowlistSupervisor):
    def reflect(self, *, allowed_tools, observations, **kwargs) -> ReflectionDecision:
        if observations[-1].tool == "project_current_plan":
            self.allowed_tool_history.append(list(allowed_tools))
            return ReflectionDecision(
                evidence_sufficient=False,
                hypothesis_status="UNCERTAIN",
                next_step="CALL_TOOL",
                next_tool="inspect_energy",
                response_source="OPENAI",
            )
        return super().reflect(
            allowed_tools=allowed_tools,
            observations=observations,
            **kwargs,
        )


class ContradictoryToolNarrativeSupervisor(RecordingAllowlistSupervisor):
    def assess(self, **kwargs) -> SupervisorTurn:
        turn = super().assess(**kwargs)
        return SupervisorTurn(
            assessment=turn.assessment,
            decision=ToolDecision(decision="STOP", tool_name=None),
            action=turn.action,
        )

    def reflect(self, *, allowed_tools, **kwargs) -> ReflectionDecision:
        reflection = super().reflect(allowed_tools=allowed_tools, **kwargs)
        if not allowed_tools:
            return reflection
        return reflection.model_copy(update={
            "next_step": "STOP_INSUFFICIENT_EVIDENCE",
            "next_tool": allowed_tools[0],
            "public_summary": (
                "Thiáº¿u káº¿t quáº£ tool; bÆ°á»›c tiáº¿p theo lÃ  gá»i tool Ä‘Æ°á»£c pháº§n phá»‘i."
            ),
        })


def test_soc_event_collects_diagnostics_before_candidate() -> None:
    outcome = ReplanningService(planner=RecordingPlanner()).process(
        previous_context=context(),
        telemetry=telemetry(),
        events=[event("event-soc-loop", "SOC_UNDERPERFORMANCE")],
    )

    assert [run.tool for run in outcome.tool_runs] == [
        "project_current_plan",
        "inspect_energy",
        "nearest_station_reachability",
        "build_full_replan",
        "compare_plans",
    ]
    assert [item.stage for item in outcome.decision_trace].count("REFLECTING") >= 3
    assert outcome.assessment.primary_objective == "PROTECT_RESERVE_SOC"
    assert all(item.public_summary for item in outcome.decision_trace)


def test_supervisor_can_choose_event_specific_diagnostic_order() -> None:
    outcome = ReplanningService(
        planner=RecordingPlanner(), supervisor=ModelOrderedSupervisor(),
    ).process(
        previous_context=context(),
        telemetry=telemetry(),
        events=[
            event("event-route-ai-order", "ROUTE_DEVIATION"),
            event("event-station-ai-order", "STATION_UNAVAILABLE", ["ST-10"]),
        ],
    )

    assert [run.tool for run in outcome.tool_runs] == [
        "inspect_stations",
        "project_current_plan",
        "inspect_route",
        "build_minimal_substitution",
        "compare_plans",
    ]
    assert all(
        item.response_source == "OPENAI"
        for item in outcome.decision_trace
        if item.stage == "REFLECTING"
    )


def test_supervisor_receives_only_the_next_mandatory_tool() -> None:
    supervisor = RecordingAllowlistSupervisor()
    outcome = ReplanningService(
        planner=RecordingPlanner(), supervisor=supervisor,
    ).process(
        previous_context=context(),
        telemetry=telemetry(),
        events=[
            event("event-route-ordered", "ROUTE_DEVIATION"),
            event("event-soc-ordered", "SOC_UNDERPERFORMANCE"),
        ],
    )

    assert [run.tool for run in outcome.tool_runs] == [
        "project_current_plan",
        "inspect_route",
        "inspect_energy",
        "nearest_station_reachability",
        "build_full_replan",
        "compare_plans",
    ]
    assert supervisor.allowed_tool_history == [
        [
            "project_current_plan", "inspect_route", "inspect_energy",
            "nearest_station_reachability",
        ],
        ["inspect_route", "inspect_energy", "nearest_station_reachability"],
        ["inspect_energy", "nearest_station_reachability"],
        ["nearest_station_reachability"],
        [],
        ["build_full_replan"],
        ["compare_plans"],
        [],
    ]


def test_simulated_telemetry_is_input_not_an_ai_selected_tool() -> None:
    supervisor = RecordingAllowlistSupervisor()

    outcome = ReplanningService(
        planner=RecordingPlanner(), supervisor=supervisor,
    ).process(
        previous_context=context(),
        telemetry=telemetry(),
        events=[
            event("event-auto-route", "ROUTE_DEVIATION"),
            event("event-auto-soc", "SOC_UNDERPERFORMANCE"),
            event("event-auto-station", "STATION_UNAVAILABLE", ["ST-10"]),
        ],
    )

    assert outcome.status == "SUCCEEDED"
    assert "inspect_telemetry" not in [run.tool for run in outcome.tool_runs]
    assert supervisor.allowed_tool_history[0] == [
        "project_current_plan", "inspect_route", "inspect_energy",
        "nearest_station_reachability", "inspect_stations",
    ]
    assert "telemetry:telemetry-5" in {
        ref for run in outcome.tool_runs for ref in run.provenance_refs
    }


def test_contradictory_ai_tool_decisions_cannot_block_deterministic_f1_flow() -> None:
    outcome = ReplanningService(
        planner=RecordingPlanner(), supervisor=ContradictoryToolNarrativeSupervisor(),
    ).process(
        previous_context=context(),
        telemetry=telemetry(),
        events=[
            event("event-deterministic-route", "ROUTE_DEVIATION"),
            event("event-deterministic-soc", "SOC_UNDERPERFORMANCE"),
            event(
                "event-deterministic-station",
                "STATION_UNAVAILABLE",
                ["ST-10"],
            ),
        ],
    )

    assert outcome.status == "SUCCEEDED"
    assert [run.tool for run in outcome.tool_runs] == [
        "project_current_plan",
        "inspect_route",
        "inspect_energy",
        "nearest_station_reachability",
        "inspect_stations",
        "build_minimal_substitution",
        "compare_plans",
    ]
    assert outcome.candidate is not None
    assert outcome.action.action == "PROPOSE_REPLAN"


def test_out_of_order_ai_assessment_does_not_override_deterministic_order() -> None:
    planner = RecordingPlanner()
    outcome = ReplanningService(
        planner=planner, supervisor=OutOfOrderInitialSupervisor(),
    ).process(
        previous_context=context(), telemetry=telemetry(),
        events=[event("event-route-initial-order", "ROUTE_DEVIATION")],
    )

    assert outcome.status == "SUCCEEDED"
    assert [run.tool for run in outcome.tool_runs] == [
        "inspect_route", "project_current_plan",
        "build_full_replan", "compare_plans",
    ]
    assert len(planner.calls) == 1


def test_out_of_order_ai_reflection_does_not_override_deterministic_order() -> None:
    planner = RecordingPlanner()
    outcome = ReplanningService(
        planner=planner, supervisor=OutOfOrderReflectionSupervisor(),
    ).process(
        previous_context=context(), telemetry=telemetry(),
        events=[event("event-route-reflection-order", "ROUTE_DEVIATION")],
    )

    assert outcome.status == "SUCCEEDED"
    assert [run.tool for run in outcome.tool_runs] == [
        "project_current_plan", "inspect_route",
        "build_full_replan", "compare_plans",
    ]
    assert len(planner.calls) == 1


def test_unknown_ai_tool_choice_does_not_block_deterministic_f1_flow() -> None:
    planner = RecordingPlanner()
    outcome = ReplanningService(
        planner=planner, supervisor=InvalidToolSupervisor(),
    ).process(
        previous_context=context(), telemetry=telemetry(),
        events=[event("event-invalid-tool", "ROUTE_DEVIATION")],
    )

    assert outcome.status == "SUCCEEDED"
    assert outcome.action.action == "PROPOSE_REPLAN"
    assert [run.tool for run in outcome.tool_runs] == [
        "project_current_plan", "inspect_route",
        "build_full_replan", "compare_plans",
    ]
    assert len(planner.calls) == 1


def test_decision_trace_callback_emits_each_public_step_in_order() -> None:
    emitted = []
    outcome = ReplanningService(
        planner=RecordingPlanner(), on_trace=emitted.append,
    ).process(
        previous_context=context(), telemetry=telemetry(),
        events=[event("event-soc-stream", "SOC_UNDERPERFORMANCE")],
    )

    assert [item.sequence for item in emitted] == [
        item.sequence for item in outcome.decision_trace
    ]
    assert emitted[-1].stage == "GUARDING_ACTION"


def test_coalesced_events_use_union_of_diagnostics_and_keep_blacklist() -> None:
    planner = RecordingPlanner()
    outcome = ReplanningService(planner=planner).process(
        previous_context=context(),
        telemetry=telemetry(),
        events=[
            event("event-route-loop", "ROUTE_DEVIATION"),
            event("event-station-loop", "STATION_UNAVAILABLE", ["ST-10"]),
        ],
    )

    assert [run.tool for run in outcome.tool_runs] == [
        "project_current_plan",
        "inspect_route",
        "inspect_stations",
        "build_minimal_substitution",
        "compare_plans",
    ]
    assert planner.calls[0]["excluded_station_ids"] == ["ST-10"]
    station_step = next(
        item for item in outcome.decision_trace if item.tool == "inspect_stations"
    )
    assert "station:ST-10:excluded" in station_step.evidence_refs


def test_stale_simulated_telemetry_stops_before_agent_tools() -> None:
    planner = RecordingPlanner()
    outcome = ReplanningService(planner=planner).process(
        previous_context=context(),
        telemetry=telemetry(),
        events=[event("event-stale-loop", "STALE_TELEMETRY")],
    )

    assert outcome.tool_runs == []
    assert planner.calls == []
    assert outcome.decision_trace[-1].status == "BLOCKED"


def test_public_trace_has_no_private_reasoning_field() -> None:
    outcome = ReplanningService(planner=RecordingPlanner()).process(
        previous_context=context(),
        telemetry=telemetry(),
        events=[event("event-route-trace", "ROUTE_DEVIATION")],
    )

    payload = outcome.model_dump(mode="json")
    assert "decision_trace" in payload
    assert all("chain_of_thought" not in item for item in payload["decision_trace"])
    assert all("reasoning" not in item for item in payload["decision_trace"])
