from __future__ import annotations

from typing import Literal, Protocol


SimulationFault = Literal[
    "NONE",
    "F1_PROVIDER_FAILURE",
    "F1_PROVEN_INFEASIBLE",
]


class CandidatePlanner(Protocol):
    def project_remaining_plan(self, **kwargs) -> dict: ...

    def build_candidate(self, **kwargs) -> dict: ...


class SimulationFaultCandidatePlanner:
    """Inject typed F1 outcomes at the F4 composition boundary only."""

    def __init__(self, delegate: CandidatePlanner, fault: SimulationFault):
        self._delegate = delegate
        self._fault = fault

    def project_remaining_plan(self, **kwargs) -> dict:
        return self._delegate.project_remaining_plan(**kwargs)

    def build_candidate(self, **kwargs) -> dict:
        strategy = kwargs.get("strategy", "FULL_REPLAN")
        if self._fault == "NONE":
            return self._delegate.build_candidate(**kwargs)
        if self._fault == "F1_PROVIDER_FAILURE":
            return {
                "feasibility_verdict": "INSUFFICIENT_EVIDENCE",
                "provider_status": "SIMULATED_PROVIDER_FAILURE",
                "reason_codes": ["SIMULATED_F1_PROVIDER_FAILURE"],
                "strategy": strategy,
            }
        return {
            "feasibility_verdict": "INFEASIBLE",
            "provider_status": None,
            "reason_codes": ["SIMULATED_PROVEN_INFEASIBLE"],
            "strategy": strategy,
        }
