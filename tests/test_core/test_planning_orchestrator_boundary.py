from src.packages.core.planning.application.orchestrator import (
    PlanningExecution,
    PlanningRequest,
)
from src.packages.core.planning.domain.outcomes import PlanningOutcomeKind


def test_planning_request_carries_replanning_station_blacklist():
    request = PlanningRequest(
        trip_id="trip-1", owner_id="owner-1", origin_name="A", origin_lat=21.0,
        origin_lng=105.0, destination_name="B", destination_lat=18.0,
        destination_lng=105.0, initial_soc_percent=50.0,
        vehicle_profile=object(), assumptions=object(), excluded_station_ids=["ST-10"],
    )

    assert request.to_state()["excluded_station_ids"] == ["ST-10"]


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
