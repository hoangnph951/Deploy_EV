from src.packages.core.planning.application.orchestrator import (
    PlanningExecution,
    PlanningRequest,
)
from src.packages.core.planning.domain.outcomes import PlanningOutcomeKind


def test_planning_execution_classifies_success() -> None:
    execution = PlanningExecution(state={"plan_proposal": object()})

    assert execution.outcome == PlanningOutcomeKind.SUCCEEDED


def test_planning_execution_classifies_user_action_diagnostics() -> None:
    execution = PlanningExecution(
        state={
            "no_feasible_plan": object(),
            "station_routing_rate_limited": True,
        }
    )

    assert execution.outcome == PlanningOutcomeKind.REQUIRES_USER_ACTION


def test_planning_request_maps_explicit_context_to_graph_state() -> None:
    request_fields = set(PlanningRequest.__dataclass_fields__)

    assert "trip_id" in request_fields
    assert "vehicle_profile" in request_fields
    assert "assumptions" in request_fields
    assert "query" not in request_fields
