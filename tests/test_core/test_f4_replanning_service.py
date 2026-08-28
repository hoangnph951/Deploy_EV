from datetime import UTC, datetime

from src.packages.agent.replanning.fallback import ConservativeSupervisor
from src.packages.agent.replanning.schemas import ActionProposalDraft
from src.packages.contracts.monitoring import MonitoringEvent, TelemetrySnapshot
from src.packages.contracts.replanning import ActiveConstraintContext, TripContextSnapshot
from src.packages.core.replanning.application.service import ReplanningService

NOW = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)


class RecordingPlanner:
    def __init__(self, verdict="FEASIBLE", *, projection=None, strategy_verdicts=None):
        self.calls = []
        self.verdict = verdict
        self.projection = projection or {
            "remaining_station_ids": ["ST-10"],
            "affected_excluded_station_ids": ["ST-10"],
            "unaffected_remaining_station_ids": [],
            "station_unavailable_affects_remaining_trip": True,
        }
        self.strategy_verdicts = strategy_verdicts or {}

    def project_remaining_plan(self, **kwargs):
        return self.projection

    def build_candidate(self, **kwargs):
        self.calls.append(kwargs)
        verdict = self.strategy_verdicts.get(kwargs.get("strategy"), self.verdict)
        return {
            "plan_version": 5,
            "feasibility_verdict": verdict,
            "strategy": kwargs.get("strategy"),
        }


def context() -> TripContextSnapshot:
    return TripContextSnapshot(
        trip_id="trip-1", context_version=4, current_confirmed_plan_version=3,
        pending_plan_version=None, telemetry_snapshot_id="telemetry-4",
        current_lat=21.0, current_lng=105.0, current_soc_percent=50,
        destination_lat=18.7, destination_lng=105.7,
        vehicle_profile_version="vf6-v1", policy_version="policy-v1",
        assumption_snapshot_id="assumption-1", active_event_ids=[],
        unresolved_constraints=ActiveConstraintContext(), created_at=NOW,
    )


def telemetry() -> TelemetrySnapshot:
    return TelemetrySnapshot(
        snapshot_id="telemetry-5", lat=20.9, lon=105.1, soc_percent=40,
        expected_soc_percent=48, speed_kph=50, distance_km=30,
        progress_percent=20, recorded_at=NOW,
    )


def event(event_id: str, event_type: str, station_ids=None):
    return MonitoringEvent(
        event_id=event_id, trip_id="trip-1", event_type=event_type,
        occurred_at=NOW, received_at=NOW, telemetry_snapshot_id="telemetry-5",
        related_plan_version=3, severity="HIGH", evidence_refs=[event_id],
        correlation_id="corr-1", station_ids=station_ids or [],
    )


def test_multi_event_run_builds_at_most_one_candidate_with_blacklist() -> None:
    planner = RecordingPlanner()
    outcome = ReplanningService(planner=planner).process(
        previous_context=context(), telemetry=telemetry(),
        events=[
            event("event-soc", "SOC_UNDERPERFORMANCE"),
            event("event-station", "STATION_UNAVAILABLE", ["ST-10"]),
        ],
    )
    assert outcome.status == "SUCCEEDED"
    assert outcome.context.context_version == 5
    assert len(outcome.epoch.event_ids) == 2
    assert len(planner.calls) == 1
    assert planner.calls[0]["excluded_station_ids"] == ["ST-10"]
    assert [run.tool for run in outcome.tool_runs] == [
        "inspect_telemetry", "project_current_plan", "inspect_energy",
        "nearest_station_reachability", "inspect_stations",
        "build_minimal_substitution", "compare_plans",
    ]
    assert outcome.tool_runs[-2].provider == "F1_PLANNING_ORCHESTRATOR"
    assert outcome.reflection.evidence_sufficient is True
    assert outcome.reflection.next_step == "PROPOSE_ACTION"


def test_station_no_longer_in_remaining_trip_continues_current_plan() -> None:
    planner = RecordingPlanner(projection={
        "remaining_station_ids": ["ST-20"],
        "affected_excluded_station_ids": [],
        "unaffected_remaining_station_ids": ["ST-20"],
        "station_unavailable_affects_remaining_trip": False,
    })

    outcome = ReplanningService(planner=planner).process(
        previous_context=context(), telemetry=telemetry(),
        events=[event("event-past-station", "STATION_UNAVAILABLE", ["ST-10"])],
    )

    assert outcome.status == "SUCCEEDED"
    assert outcome.action.action == "CONTINUE_CURRENT_PLAN"
    assert outcome.action.requires_owner_confirmation is False
    assert outcome.candidate is None
    assert planner.calls == []
    assert [run.tool for run in outcome.tool_runs] == [
        "inspect_telemetry", "project_current_plan",
    ]


def test_station_impact_tries_minimal_substitution_before_full_replan() -> None:
    planner = RecordingPlanner(strategy_verdicts={
        "MINIMAL_SUBSTITUTION": "STRATEGY_NOT_SATISFIED",
        "FULL_REPLAN": "FEASIBLE",
    })

    outcome = ReplanningService(planner=planner).process(
        previous_context=context(), telemetry=telemetry(),
        events=[event("event-fallback-station", "STATION_UNAVAILABLE", ["ST-10"])],
    )

    assert [call["strategy"] for call in planner.calls] == [
        "MINIMAL_SUBSTITUTION", "FULL_REPLAN",
    ]
    assert [run.tool for run in outcome.tool_runs][-3:] == [
        "build_minimal_substitution", "build_full_replan", "compare_plans",
    ]
    assert outcome.candidate["strategy"] == "FULL_REPLAN"
    assert outcome.action.action == "PROPOSE_REPLAN"
    assert outcome.action.requires_owner_confirmation is True


def test_unaffected_station_does_not_hide_another_active_replan_event() -> None:
    planner = RecordingPlanner(projection={
        "remaining_station_ids": ["ST-20"],
        "affected_excluded_station_ids": [],
        "unaffected_remaining_station_ids": ["ST-20"],
        "station_unavailable_affects_remaining_trip": False,
    })

    outcome = ReplanningService(planner=planner).process(
        previous_context=context(), telemetry=telemetry(),
        events=[
            event("event-unaffected-station", "STATION_UNAVAILABLE", ["ST-10"]),
            event("event-active-soc", "SOC_UNDERPERFORMANCE"),
        ],
    )

    assert outcome.action.action == "PROPOSE_REPLAN"
    assert [call["strategy"] for call in planner.calls] == ["FULL_REPLAN"]


def test_stale_telemetry_blocks_candidate_generation() -> None:
    planner = RecordingPlanner()
    outcome = ReplanningService(planner=planner).process(
        previous_context=context(), telemetry=telemetry(),
        events=[event("event-stale", "STALE_TELEMETRY")],
    )
    assert outcome.status == "INSUFFICIENT_EVIDENCE"
    assert outcome.action.action == "REQUEST_NEW_TELEMETRY"
    assert planner.calls == []
    assert [run.tool for run in outcome.tool_runs] == ["inspect_telemetry"]


def test_provider_failure_is_insufficient_evidence_not_infeasible() -> None:
    outcome = ReplanningService(planner=RecordingPlanner("INSUFFICIENT_EVIDENCE")).process(
        previous_context=context(), telemetry=telemetry(),
        events=[event("event-route", "ROUTE_DEVIATION")],
    )
    assert outcome.status == "INSUFFICIENT_EVIDENCE"
    assert outcome.action.action == "STOP_INSUFFICIENT_EVIDENCE"
    assert outcome.reflection.next_step == "STOP_INSUFFICIENT_EVIDENCE"


def test_exhausted_search_budget_is_not_infeasible() -> None:
    outcome = ReplanningService(planner=RecordingPlanner("SEARCH_EXHAUSTED")).process(
        previous_context=context(), telemetry=telemetry(),
        events=[event("event-soc-search", "SOC_UNDERPERFORMANCE")],
    )
    assert outcome.status == "SEARCH_EXHAUSTED"
    assert outcome.reflection.next_step == "STOP_SEARCH_EXHAUSTED"


class DraftingSupervisor(ConservativeSupervisor):
    def __init__(self, draft: ActionProposalDraft):
        self.draft = draft
        self.draft_calls = 0

    def draft_action(self, **kwargs) -> ActionProposalDraft:
        self.draft_calls += 1
        return self.draft


def test_service_uses_supervisor_action_draft_after_deterministic_feasibility() -> None:
    supervisor = DraftingSupervisor(ActionProposalDraft(
        action="PROPOSE_CONDITIONAL_REPLAN",
        reason_codes=["AGENT_SELECTED_CONDITIONAL_REPLAN"],
        evidence_refs=["evidence:agent-draft"],
        user_message="Phương án mới cần được xác nhận sau khi kiểm tra điều kiện.",
        limitations=["Điều kiện thử nghiệm"],
        requires_owner_confirmation=True,
    ))

    outcome = ReplanningService(
        planner=RecordingPlanner(), supervisor=supervisor,
    ).process(
        previous_context=context(), telemetry=telemetry(),
        events=[event("event-route-draft", "ROUTE_DEVIATION")],
    )

    assert supervisor.draft_calls == 1
    assert outcome.action.action == "PROPOSE_CONDITIONAL_REPLAN"
    assert outcome.action.reason_codes == ["AGENT_SELECTED_CONDITIONAL_REPLAN"]


def test_service_falls_back_when_supervisor_action_draft_breaks_safety_guard() -> None:
    supervisor = DraftingSupervisor(ActionProposalDraft(
        action="PROPOSE_REPLAN",
        reason_codes=["UNSAFE_AGENT_DRAFT"],
        evidence_refs=[],
        user_message="Bản nháp không hợp lệ.",
        limitations=[],
        requires_owner_confirmation=False,
    ))

    outcome = ReplanningService(
        planner=RecordingPlanner(), supervisor=supervisor,
    ).process(
        previous_context=context(), telemetry=telemetry(),
        events=[event("event-route-fallback", "ROUTE_DEVIATION")],
    )

    assert supervisor.draft_calls == 1
    assert outcome.action.action == "PROPOSE_REPLAN"
    assert outcome.action.requires_owner_confirmation is True
