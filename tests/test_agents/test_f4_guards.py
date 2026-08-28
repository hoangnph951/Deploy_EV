from src.packages.agent.replanning.action_guard import ActionGuard
from src.packages.agent.replanning.policy_guard import ToolPolicyGuard
from src.packages.agent.replanning.schemas import ActionProposalDraft, ToolDecision
from src.packages.contracts.replanning import ActiveConstraintContext


def tool(name: str, arguments: dict | None = None) -> ToolDecision:
    return ToolDecision(
        decision="CALL_TOOL",
        tool_name=name,
        arguments=arguments or {},
        expected_evidence=["typed-observation"],
        reason_codes=["INVESTIGATE"],
        evidence_refs=[],
    )


def test_stale_telemetry_blocks_planning_tools() -> None:
    result = ToolPolicyGuard().validate(
        tool("build_candidate"),
        active_constraints=ActiveConstraintContext(telemetry_blocked=True),
        tool_budget_remaining=6,
    )
    assert result.allowed is False
    assert result.reason_code == "TELEMETRY_BLOCKED"


def test_station_blacklist_must_be_propagated() -> None:
    result = ToolPolicyGuard().validate(
        tool("build_candidate", {"excluded_station_ids": []}),
        active_constraints=ActiveConstraintContext(excluded_station_ids=["ST-10"]),
        tool_budget_remaining=6,
    )
    assert result.allowed is False
    assert result.reason_code == "BLACKLIST_NOT_PROPAGATED"

    minimal = ToolPolicyGuard().validate(
        tool("build_minimal_substitution", {"excluded_station_ids": []}),
        active_constraints=ActiveConstraintContext(excluded_station_ids=["ST-10"]),
        tool_budget_remaining=6,
    )
    assert minimal.reason_code == "BLACKLIST_NOT_PROPAGATED"


def test_invalid_or_over_budget_tool_is_rejected() -> None:
    guard = ToolPolicyGuard()
    assert guard.validate(
        tool("delete_plan"), active_constraints=ActiveConstraintContext(), tool_budget_remaining=6
    ).reason_code == "TOOL_NOT_ALLOWED"
    assert guard.validate(
        tool("project_current_plan"),
        active_constraints=ActiveConstraintContext(),
        tool_budget_remaining=0,
    ).reason_code == "TOOL_BUDGET_EXHAUSTED"


def test_action_cannot_continue_after_deterministic_infeasible() -> None:
    draft = ActionProposalDraft(
        action="CONTINUE_CURRENT_PLAN",
        reason_codes=["MODEL_RECOMMENDATION"],
        evidence_refs=["feasibility:1"],
        user_message="Continue",
        limitations=[],
        requires_owner_confirmation=False,
    )
    result = ActionGuard().validate(draft, feasibility_verdict="INFEASIBLE")
    assert result.allowed is False
    assert result.reason_code == "INFEASIBLE_OVERRIDE_FORBIDDEN"


def test_action_cannot_propose_replan_without_sufficient_safety_evidence() -> None:
    draft = ActionProposalDraft(
        action="PROPOSE_REPLAN", reason_codes=[], evidence_refs=[],
        user_message="Đề xuất không có đủ bằng chứng.", limitations=[],
        requires_owner_confirmation=True,
    )

    result = ActionGuard().validate(
        draft, feasibility_verdict="INSUFFICIENT_EVIDENCE",
    )

    assert result.allowed is False
    assert result.reason_code == "SAFETY_EVIDENCE_REQUIRED"


def test_action_cannot_continue_when_station_still_affects_remaining_trip() -> None:
    draft = ActionProposalDraft(
        action="CONTINUE_CURRENT_PLAN", reason_codes=["MODEL_RECOMMENDATION"],
        evidence_refs=[], user_message="Tiếp tục.", limitations=[],
        requires_owner_confirmation=False,
    )

    result = ActionGuard().validate(
        draft,
        feasibility_verdict=None,
        station_unavailable_affects_remaining_trip=True,
    )

    assert result.allowed is False
    assert result.reason_code == "AFFECTED_STATION_REQUIRES_REPLAN"


def test_action_cannot_replan_when_failed_station_is_not_in_remaining_trip() -> None:
    draft = ActionProposalDraft(
        action="PROPOSE_REPLAN", reason_codes=["MODEL_RECOMMENDATION"],
        evidence_refs=[], user_message="Lập lại.", limitations=[],
        requires_owner_confirmation=True,
    )

    result = ActionGuard().validate(
        draft,
        feasibility_verdict="FEASIBLE",
        station_unavailable_affects_remaining_trip=False,
    )

    assert result.allowed is False
    assert result.reason_code == "UNAFFECTED_STATION_MUST_PRESERVE_CURRENT_PLAN"
