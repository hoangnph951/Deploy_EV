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
        return SupervisorTurn(
            assessment=turn.assessment,
            decision=ToolDecision(
                decision="CALL_TOOL",
                tool_name="inspect_telemetry",
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


def test_soc_event_collects_diagnostics_before_candidate() -> None:
    outcome = ReplanningService(planner=RecordingPlanner()).process(
        previous_context=context(),
        telemetry=telemetry(),
        events=[event("event-soc-loop", "SOC_UNDERPERFORMANCE")],
    )

    assert [run.tool for run in outcome.tool_runs] == [
        "inspect_telemetry",
        "project_current_plan",
        "inspect_energy",
        "nearest_station_reachability",
        "build_full_replan",
        "compare_plans",
    ]
    assert [item.stage for item in outcome.decision_trace].count("REFLECTING") >= 3
    assert outcome.assessment.primary_objective == "PROTECT_RESERVE_SOC"
    assert all(item.public_summary for item in outcome.decision_trace)


def test_supervisor_selects_tool_order_from_the_allowed_runtime_set() -> None:
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
        "inspect_telemetry",
        "inspect_stations",
        "project_current_plan",
        "inspect_route",
        "build_minimal_substitution",
        "compare_plans",
    ]


def test_invalid_ai_tool_choice_fails_closed_without_local_replacement() -> None:
    planner = RecordingPlanner()
    outcome = ReplanningService(
        planner=planner, supervisor=InvalidToolSupervisor(),
    ).process(
        previous_context=context(), telemetry=telemetry(),
        events=[event("event-invalid-tool", "ROUTE_DEVIATION")],
    )

    assert outcome.status == "INSUFFICIENT_EVIDENCE"
    assert outcome.action.action == "STOP_INSUFFICIENT_EVIDENCE"
    assert outcome.reflection.reason_codes == ["AI_TOOL_SELECTION_INVALID"]
    assert planner.calls == []


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
        "inspect_telemetry",
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


def test_stale_telemetry_records_check_and_stops_before_f1() -> None:
    planner = RecordingPlanner()
    outcome = ReplanningService(planner=planner).process(
        previous_context=context(),
        telemetry=telemetry(),
        events=[event("event-stale-loop", "STALE_TELEMETRY")],
    )

    assert [run.tool for run in outcome.tool_runs] == ["inspect_telemetry"]
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
