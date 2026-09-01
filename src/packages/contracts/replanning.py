from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.packages.contracts.monitoring import (
    MonitoringEvent,
    SimulationFault,
    TelemetrySnapshot,
)


ReplanAction = Literal[
    "CONTINUE_CURRENT_PLAN",
    "PROPOSE_REPLAN",
    "PROPOSE_CONDITIONAL_REPLAN",
    "INVALIDATE_CURRENT_PLAN_AND_PROPOSE_REPLAN",
    "REQUEST_NEW_TELEMETRY",
    "NO_FEASIBLE_PLAN_REQUEST_ASSISTANCE",
    "STOP_INSUFFICIENT_EVIDENCE",
]


class ActiveConstraintContext(BaseModel):
    route_deviation_active: bool = False
    soc_underperformance_active: bool = False
    telemetry_blocked: bool = False
    excluded_station_ids: list[str] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    unresolved_reason_codes: list[str] = Field(default_factory=list)


class DecisionEpoch(BaseModel):
    epoch_id: str
    trip_id: str
    telemetry_snapshot_id: str
    context_version: int = Field(ge=1)
    base_plan_version: int = Field(ge=0)
    event_ids: list[str] = Field(default_factory=list)
    opened_at: datetime
    sealed_at: datetime | None = None
    status: Literal["OPEN", "SEALED", "RUNNING", "COMPLETED", "SUPERSEDED"] = "SEALED"


class TripContextSnapshot(BaseModel):
    trip_id: str
    context_version: int = Field(ge=1)
    current_confirmed_plan_version: int = Field(ge=0)
    pending_plan_version: int | None = Field(default=None, ge=1)
    telemetry_snapshot_id: str
    current_lat: float | None = Field(default=None, ge=-90, le=90)
    current_lng: float | None = Field(default=None, ge=-180, le=180)
    current_soc_percent: float | None = Field(default=None, ge=0, le=100)
    destination_lat: float = Field(ge=-90, le=90)
    destination_lng: float = Field(ge=-180, le=180)
    vehicle_profile_version: str
    policy_version: str
    assumption_snapshot_id: str
    active_event_ids: list[str] = Field(default_factory=list)
    unresolved_constraints: ActiveConstraintContext = Field(default_factory=ActiveConstraintContext)
    created_at: datetime


class ReplanSubmissionRequest(BaseModel):
    telemetry: TelemetrySnapshot
    events: list[MonitoringEvent] = Field(min_length=1)
    simulation_fault: SimulationFault = "NONE"


class PlanDecisionRequest(BaseModel):
    expected_plan_version: int = Field(ge=1)
    expected_context_version: int = Field(ge=1)


class PlanDecisionResponse(BaseModel):
    trip_id: str
    plan_version: int
    context_version: int
    status: Literal["CONFIRMED", "REJECTED"]


# Compatibility contracts for the legacy ``simulation-runs`` demo API.  The
# primary F4 runtime uses ReplanningOutcome above, while this trace shape is
# still exposed by the simulator response and UI.
class PlanDiff(BaseModel):
    distance_delta_km: float = 0.0
    duration_delta_min: float = 0.0
    final_soc_delta_percent: float = 0.0
    removed_station_ids: list[str] = Field(default_factory=list)
    added_station_ids: list[str] = Field(default_factory=list)
    old_safety: str = "FEASIBLE"
    candidate_safety: str = "FEASIBLE"
    summary: str = ""


class CandidatePlanSummary(BaseModel):
    candidate_id: str
    status: Literal["PENDING", "CONFIRMED", "REJECTED", "STALE_BY_NEW_CONTEXT"] = "PENDING"
    generated_from_context_version: int | None = None
    generated_from_telemetry_snapshot_id: str | None = None
    base_confirmed_plan_version: int | None = None
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
        "ROUTE_RECOVERY", "ENERGY_RESCUE", "STATION_SUBSTITUTION", "TELEMETRY_RECOVERY"
    ]
    intent_confidence: float = Field(ge=0, le=1)
    classification_source: Literal["AI_AGENT", "DETERMINISTIC_FALLBACK"]
    strategy: str
    selected_tools: list[str] = Field(default_factory=list)
    events: list[MonitoringEvent] = Field(default_factory=list)
    action: ReplanAction
    action_guard: Literal["PASSED", "FALLBACK"]
    requires_owner_confirmation: bool
    reason_codes: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    explanation: str
    limitations: list[str] = Field(default_factory=list)
    plan_diff: PlanDiff | None = None
    candidate_plan: CandidatePlanSummary | None = None
    decision_epoch_id: str | None = None
    context_version: int = 1
    prompt_version: str = "f4-supervisor-v2"
    policy_version: str = "f4-policy-v2"
    safety_gate_status: Literal["PASSED", "BLOCKED", "FALLBACK"] = "PASSED"
