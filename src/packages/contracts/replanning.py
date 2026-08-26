from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from src.packages.contracts.monitoring import MonitoringEvent

ReplanAction = Literal[
    "CONTINUE_CURRENT_PLAN",
    "PROPOSE_REPLAN",
    "PROPOSE_CONDITIONAL_REPLAN",
    "INVALIDATE_CURRENT_PLAN_AND_PROPOSE_REPLAN",
    "REQUEST_NEW_TELEMETRY",
    "NO_FEASIBLE_PLAN_REQUEST_ASSISTANCE",
]


class PlanDiff(BaseModel):
    distance_delta_km: float = 0.0
    duration_delta_min: float = 0.0
    final_soc_delta_percent: float = 0.0
    removed_station_ids: list[str] = Field(default_factory=list)
    added_station_ids: list[str] = Field(default_factory=list)
    old_safety: str = "FEASIBLE"
    candidate_safety: str = "FEASIBLE"
    summary: str


class CandidatePlanSummary(BaseModel):
    candidate_id: str
    status: Literal["PENDING"] = "PENDING"
    origin_lat: float
    origin_lng: float
    destination_lat: float
    destination_lng: float
    distance_km: float = Field(ge=0)
    duration_min: float = Field(ge=0)
    final_soc_percent: float = Field(ge=0, le=100)
    station_ids: list[str] = Field(default_factory=list)
    safety_verdict: Literal["FEASIBLE", "INFEASIBLE"]
    simulation_only: bool = True


class AgentDecision(BaseModel):
    agent_run_id: str
    intent: Literal[
        "ROUTE_RECOVERY",
        "ENERGY_RESCUE",
        "STATION_SUBSTITUTION",
        "TELEMETRY_RECOVERY",
    ]
    intent_confidence: float = Field(ge=0, le=1)
    classification_source: Literal["AI_AGENT", "DETERMINISTIC_FALLBACK"]
    strategy: str
    selected_tools: list[str]
    events: list[MonitoringEvent]
    action: ReplanAction
    action_guard: Literal["PASSED", "FALLBACK"]
    requires_owner_confirmation: bool
    reason_codes: list[str]
    evidence_refs: list[str]
    explanation: str
    limitations: list[str] = Field(default_factory=list)
    plan_diff: PlanDiff | None = None
    candidate_plan: CandidatePlanSummary | None = None

