from __future__ import annotations

from src.packages.agent.replanning.policy_guard import GuardResult
from src.packages.agent.replanning.schemas import ActionProposalDraft


class ActionGuard:
    def validate(
        self,
        draft: ActionProposalDraft,
        *,
        feasibility_verdict: str | None,
        station_unavailable_affects_remaining_trip: bool | None = None,
        other_replan_event_active: bool = False,
    ) -> GuardResult:
        proposing_actions = {
            "PROPOSE_REPLAN", "PROPOSE_CONDITIONAL_REPLAN",
            "INVALIDATE_CURRENT_PLAN_AND_PROPOSE_REPLAN",
        }
        if feasibility_verdict == "INFEASIBLE" and draft.action in {
            "CONTINUE_CURRENT_PLAN", "PROPOSE_REPLAN", "PROPOSE_CONDITIONAL_REPLAN"
        }:
            return GuardResult(False, "INFEASIBLE_OVERRIDE_FORBIDDEN")
        if feasibility_verdict in {"INSUFFICIENT_EVIDENCE", "SEARCH_EXHAUSTED"} \
                and draft.action in proposing_actions:
            return GuardResult(False, "SAFETY_EVIDENCE_REQUIRED")
        if draft.action in proposing_actions and not draft.requires_owner_confirmation:
            return GuardResult(False, "OWNER_CONFIRMATION_REQUIRED")
        if (
            draft.action == "CONTINUE_CURRENT_PLAN"
            and station_unavailable_affects_remaining_trip is not False
        ):
            return GuardResult(False, "AFFECTED_STATION_REQUIRES_REPLAN")
        if (
            station_unavailable_affects_remaining_trip is False
            and not other_replan_event_active
            and draft.action != "CONTINUE_CURRENT_PLAN"
        ):
            return GuardResult(False, "UNAFFECTED_STATION_MUST_PRESERVE_CURRENT_PLAN")
        return GuardResult(True)
