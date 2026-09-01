from __future__ import annotations

from dataclasses import dataclass

from src.packages.agent.replanning.schemas import ToolDecision
from src.packages.contracts.replanning import ActiveConstraintContext

ALLOWED_TOOLS = {
    "project_current_plan", "get_verified_route", "estimate_energy",
    "search_verified_stations", "check_telemetry", "build_candidate", "compare_plans",
    "inspect_route", "inspect_energy",
    "nearest_station_reachability", "inspect_stations",
    "build_minimal_substitution", "build_full_replan",
}
PLANNING_TOOLS = ALLOWED_TOOLS - {"check_telemetry"}


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reason_code: str | None = None


class ToolPolicyGuard:
    def validate(
        self,
        decision: ToolDecision,
        *,
        active_constraints: ActiveConstraintContext,
        tool_budget_remaining: int,
    ) -> GuardResult:
        if decision.tool_name not in ALLOWED_TOOLS:
            return GuardResult(False, "TOOL_NOT_ALLOWED")
        if tool_budget_remaining <= 0:
            return GuardResult(False, "TOOL_BUDGET_EXHAUSTED")
        if active_constraints.telemetry_blocked and decision.tool_name in PLANNING_TOOLS:
            return GuardResult(False, "TELEMETRY_BLOCKED")
        if active_constraints.excluded_station_ids and decision.tool_name in {
            "search_verified_stations", "build_candidate",
            "build_minimal_substitution", "build_full_replan",
        }:
            supplied = set(decision.arguments.get("excluded_station_ids", []))
            if not set(active_constraints.excluded_station_ids).issubset(supplied):
                return GuardResult(False, "BLACKLIST_NOT_PROPAGATED")
        return GuardResult(True)
