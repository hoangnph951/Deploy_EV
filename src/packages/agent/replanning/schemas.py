from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SituationAssessment(BaseModel):
    primary_objective: Literal[
        "RESTORE_SAFE_ROUTE", "PROTECT_RESERVE_SOC", "REPLACE_UNAVAILABLE_STATION",
        "RECOVER_TELEMETRY", "PRESERVE_CURRENT_PLAN", "COMPOSITE_RECOVERY",
    ]
    urgency: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    strategy: str
    known_facts: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    public_summary: str = ""


class ToolDecision(BaseModel):
    decision: Literal["CALL_TOOL", "BUILD_CANDIDATE", "PROPOSE_ACTION", "STOP"]
    tool_name: str | None = None
    arguments: dict[str, object] = Field(default_factory=dict)
    expected_evidence: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    public_summary: str = ""


class ReflectionDecision(BaseModel):
    evidence_sufficient: bool
    hypothesis_status: Literal["SUPPORTED", "REJECTED", "UNCERTAIN"]
    missing_evidence: list[str] = Field(default_factory=list)
    next_step: Literal[
        "CALL_TOOL", "BUILD_CANDIDATE", "COMPARE_PLANS", "PROPOSE_ACTION",
        "REQUEST_TELEMETRY", "STOP_INSUFFICIENT_EVIDENCE", "STOP_SEARCH_EXHAUSTED",
    ]
    next_tool: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    public_summary: str = ""


class DiagnosticObservation(BaseModel):
    tool: str
    status: Literal["SUCCEEDED", "BLOCKED", "FAILED"]
    provider: str
    freshness: Literal["FRESH", "STALE", "NOT_APPLICABLE"]
    facts: dict[str, object] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    public_summary: str = ""


class DecisionTraceItem(BaseModel):
    sequence: int
    stage: Literal[
        "ASSESSING", "DIAGNOSING", "REFLECTING", "BUILDING_CANDIDATE",
        "COMPARING_PLANS", "PROPOSING_ACTION", "GUARDING_ACTION",
    ]
    summary_code: str
    status: str
    tool: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    public_summary: str = ""


class ActionProposalDraft(BaseModel):
    action: Literal[
        "CONTINUE_CURRENT_PLAN", "PROPOSE_REPLAN", "PROPOSE_CONDITIONAL_REPLAN",
        "INVALIDATE_CURRENT_PLAN_AND_PROPOSE_REPLAN", "REQUEST_NEW_TELEMETRY",
        "NO_FEASIBLE_PLAN_REQUEST_ASSISTANCE", "STOP_INSUFFICIENT_EVIDENCE",
    ]
    reason_codes: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    user_message: str
    limitations: list[str] = Field(default_factory=list)
    requires_owner_confirmation: bool
    public_summary: str = ""


class SupervisorStructuredTurn(BaseModel):
    assessment: SituationAssessment
    decision: ToolDecision
    action: ActionProposalDraft | None = None
