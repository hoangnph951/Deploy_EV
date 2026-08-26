from __future__ import annotations

from typing import Protocol

from src.packages.contracts.trips import PlanProposal


class SafePlanRanker(Protocol):
    """May rank/explain plans only after every plan passed the safety gate."""

    def rank(self, plans: list[PlanProposal]) -> list[PlanProposal]: ...


class DeterministicPlanRanker:
    def rank(self, plans: list[PlanProposal]) -> list[PlanProposal]:
        return plans
