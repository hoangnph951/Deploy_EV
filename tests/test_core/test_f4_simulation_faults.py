from src.packages.core.replanning.application.simulation_faults import (
    SimulationFaultCandidatePlanner,
)


class Delegate:
    def __init__(self):
        self.project_calls = []
        self.build_calls = []

    def project_remaining_plan(self, **kwargs):
        self.project_calls.append(kwargs)
        return {"delegated": True}

    def build_candidate(self, **kwargs):
        self.build_calls.append(kwargs)
        return {"feasibility_verdict": "FEASIBLE"}


def test_projection_and_none_fault_delegate_unchanged():
    delegate = Delegate()
    planner = SimulationFaultCandidatePlanner(delegate, "NONE")

    assert planner.project_remaining_plan(trip_id="trip-1") == {"delegated": True}
    assert planner.build_candidate(strategy="FULL_REPLAN") == {
        "feasibility_verdict": "FEASIBLE"
    }


def test_provider_failure_fault_is_insufficient_evidence():
    planner = SimulationFaultCandidatePlanner(Delegate(), "F1_PROVIDER_FAILURE")

    result = planner.build_candidate(strategy="FULL_REPLAN")

    assert result["feasibility_verdict"] == "INSUFFICIENT_EVIDENCE"
    assert result["provider_status"] == "SIMULATED_PROVIDER_FAILURE"


def test_proven_infeasible_fault_is_not_provider_failure():
    planner = SimulationFaultCandidatePlanner(Delegate(), "F1_PROVEN_INFEASIBLE")

    result = planner.build_candidate(strategy="FULL_REPLAN")

    assert result["feasibility_verdict"] == "INFEASIBLE"
    assert result["reason_codes"] == ["SIMULATED_PROVEN_INFEASIBLE"]
