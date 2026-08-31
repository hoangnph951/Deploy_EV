from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from src.packages.agent.replanning.action_guard import ActionGuard
from src.packages.agent.replanning.fallback import ConservativeSupervisor
from src.packages.agent.replanning.schemas import (
    ActionProposalDraft,
    DecisionTraceItem,
    ReflectionDecision,
    SituationAssessment,
)
from src.packages.contracts.monitoring import MonitoringEvent, TelemetrySnapshot
from src.packages.contracts.replanning import DecisionEpoch, TripContextSnapshot
from src.packages.core.replanning.application.context_manager import TripContextManager
from src.packages.core.replanning.application.diagnostics import required_diagnostics
from src.packages.core.replanning.application.event_coordinator import EventCoordinator
from src.packages.core.replanning.application.supervisor_loop import SupervisorLoop


class CandidatePlanner(Protocol):
    def project_remaining_plan(self, **kwargs) -> dict: ...

    def build_candidate(self, **kwargs) -> dict: ...


class ToolRunSummary(BaseModel):
    sequence: int
    tool: str
    status: str
    provider: str
    freshness: str
    provenance_refs: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class ReplanningOutcome(BaseModel):
    agent_run_id: str
    status: str
    epoch: DecisionEpoch
    context: TripContextSnapshot
    assessment: SituationAssessment
    action: ActionProposalDraft
    candidate: dict | None = None
    tool_runs: list[ToolRunSummary] = Field(default_factory=list)
    decision_trace: list[DecisionTraceItem] = Field(default_factory=list)
    plan_diff_id: str | None = None
    plan_diff: dict | None = None
    reflection: ReflectionDecision
    created_at: datetime


class ReplanningService:
    def __init__(
        self, *, planner: CandidatePlanner, supervisor=None,
        on_trace: Callable[[DecisionTraceItem], None] | None = None,
    ):
        self._planner = planner
        self._supervisor = supervisor or ConservativeSupervisor()
        self._on_trace = on_trace

    def process(
        self,
        *,
        previous_context: TripContextSnapshot,
        telemetry: TelemetrySnapshot,
        events: list[MonitoringEvent],
    ) -> ReplanningOutcome:
        coordination = EventCoordinator().coordinate(
            events,
            context_version=previous_context.context_version + 1,
            active_constraints=previous_context.unresolved_constraints,
        )
        context_result = TripContextManager().advance(
            previous=previous_context, events=events, telemetry=telemetry
        )
        event_types = [item.event_type for item in coordination.events]
        allowed_tools = required_diagnostics(event_types)
        turn = self._supervisor.assess(
            event_types=event_types,
            active_constraints=context_result.snapshot.unresolved_constraints,
            allowed_tools=allowed_tools,
            context=context_result.snapshot,
            telemetry=telemetry,
        )
        now = datetime.now(UTC)
        loop = SupervisorLoop(
            planner=self._planner, supervisor=self._supervisor, on_trace=self._on_trace,
        ).run(
            event_types=event_types,
            context=context_result.snapshot,
            telemetry=telemetry,
            assessment=turn.assessment,
            initial_decision=turn.decision,
        )
        tool_runs = [ToolRunSummary(
            sequence=index,
            tool=observation.tool,
            status=observation.status,
            provider=observation.provider,
            freshness=observation.freshness,
            provenance_refs=observation.evidence_refs,
            reason_codes=observation.reason_codes,
        ) for index, observation in enumerate(loop.observations, start=1)]
        if loop.continue_current_plan:
            reflection = loop.reflection or ReflectionDecision(
                evidence_sufficient=True, hypothesis_status="SUPPORTED",
                missing_evidence=[], next_step="PROPOSE_ACTION", next_tool=None,
                reason_codes=["UNAVAILABLE_STATION_NOT_IN_REMAINING_TRIP"],
                evidence_refs=[],
                public_summary="Trạm bị loại không còn ảnh hưởng phần hành trình phía trước.",
            )
            deterministic_action = ConservativeSupervisor().draft_action(
                feasibility_verdict="CURRENT_PLAN_UNAFFECTED",
                observations=loop.observations,
                plan_diff=None,
            )
            try:
                drafted_action = self._supervisor.draft_action(
                    feasibility_verdict="CURRENT_PLAN_UNAFFECTED",
                    observations=loop.observations,
                    plan_diff=None,
                    operational_context={
                        "event_types": event_types,
                        "assessment": turn.assessment.model_dump(mode="json"),
                        "trip_context": context_result.snapshot.model_dump(mode="json"),
                        "telemetry": telemetry.model_dump(mode="json"),
                        "final_reflection": reflection.model_dump(mode="json"),
                    },
                )
            except Exception:
                drafted_action = deterministic_action
            draft_guard = ActionGuard().validate(
                drafted_action,
                feasibility_verdict=None,
                station_unavailable_affects_remaining_trip=False,
            )
            action = drafted_action if draft_guard.allowed else deterministic_action
            loop.decision_trace.extend([
                DecisionTraceItem(
                    sequence=len(loop.decision_trace) + 1,
                    stage="PROPOSING_ACTION", summary_code="CONTINUE_CURRENT_PLAN_DRAFTED",
                    status="SUCCEEDED" if draft_guard.allowed else "BLOCKED",
                    evidence_refs=action.evidence_refs,
                    reason_codes=action.reason_codes,
                    response_source=action.response_source,
                    public_summary=action.user_message,
                ),
                DecisionTraceItem(
                    sequence=len(loop.decision_trace) + 2,
                    stage="GUARDING_ACTION", summary_code="ACTION_SAFETY_GUARD_PASSED",
                    status="SUCCEEDED", evidence_refs=action.evidence_refs,
                    reason_codes=action.reason_codes,
                    public_summary="ActionGuard xác nhận trạm lỗi không còn ảnh hưởng; giữ kế hoạch hiện tại.",
                ),
            ])
            if self._on_trace is not None:
                self._on_trace(loop.decision_trace[-2])
                self._on_trace(loop.decision_trace[-1])
            return ReplanningOutcome(
                agent_run_id=str(uuid4()), status="SUCCEEDED",
                epoch=coordination.epoch, context=context_result.snapshot,
                assessment=turn.assessment, action=action, candidate=None,
                tool_runs=tool_runs, decision_trace=loop.decision_trace,
                reflection=reflection, created_at=now,
            )
        if loop.blocked:
            telemetry_blocked = (
                context_result.snapshot.unresolved_constraints.telemetry_blocked
                or "TELEMETRY_BLOCKED" in loop.blocked_reason_codes
            )
            action = turn.action if telemetry_blocked else None
            if action is None:
                action = ActionProposalDraft(
                    action=(
                        "REQUEST_NEW_TELEMETRY" if telemetry_blocked
                        else "STOP_INSUFFICIENT_EVIDENCE"
                    ),
                    reason_codes=loop.blocked_reason_codes or ["AI_DECISION_BLOCKED"],
                    evidence_refs=[],
                    user_message=(
                        "Cần telemetry GPS và SOC mới trước khi tiếp tục."
                        if telemetry_blocked
                        else "Trợ lý chưa chọn được bước tiếp theo hợp lệ; hệ thống đã dừng an toàn."
                    ),
                    limitations=["Không tự chọn thay công cụ khi quyết định AI không hợp lệ."],
                    requires_owner_confirmation=False,
                    public_summary=loop.blocked_summary,
                )
            reflection = ReflectionDecision(
                evidence_sufficient=False, hypothesis_status="UNCERTAIN",
                missing_evidence=(
                    loop.blocked_missing_evidence
                    or (["FRESH_GPS", "FRESH_SOC"] if telemetry_blocked else ["VALID_AI_DECISION"])
                ),
                next_step=("REQUEST_TELEMETRY" if telemetry_blocked else "STOP_INSUFFICIENT_EVIDENCE"),
                next_tool=None,
                reason_codes=loop.blocked_reason_codes or ["AI_DECISION_BLOCKED"],
                evidence_refs=[],
                public_summary=(
                    loop.blocked_summary
                    or "Dữ liệu an toàn chưa hợp lệ; hệ thống đã dừng trước khi lập lại kế hoạch."
                ),
            )
            return ReplanningOutcome(
                agent_run_id=str(uuid4()), status="INSUFFICIENT_EVIDENCE",
                epoch=coordination.epoch, context=context_result.snapshot,
                assessment=turn.assessment, action=action, created_at=now,
                tool_runs=tool_runs,
                decision_trace=loop.decision_trace,
                reflection=reflection,
            )
        candidate = loop.candidate or {}
        verdict = candidate.get("feasibility_verdict")
        if verdict == "INFEASIBLE":
            action = ActionProposalDraft(
                action="NO_FEASIBLE_PLAN_REQUEST_ASSISTANCE",
                reason_codes=["DETERMINISTIC_INFEASIBLE"], evidence_refs=[],
                public_summary=(
                    loop.reflection.public_summary if loop.reflection else
                    "Bằng chứng tất định bác bỏ phương án mới; không được đề xuất áp dụng."
                ),
                user_message="Không tìm thấy phương án đã được chứng minh an toàn.",
                limitations=[], requires_owner_confirmation=False,
            )
            status = "INFEASIBLE"
            reflection = ReflectionDecision(
                evidence_sufficient=True, hypothesis_status="REJECTED",
                missing_evidence=[], next_step="PROPOSE_ACTION", next_tool=None,
                reason_codes=["DETERMINISTIC_INFEASIBLE"], evidence_refs=[],
                public_summary=(
                    loop.reflection.public_summary if loop.reflection else
                    "Bằng chứng tất định bác bỏ phương án mới; không được đề xuất áp dụng."
                ),
            )
        elif verdict == "INSUFFICIENT_EVIDENCE":
            action = ActionProposalDraft(
                action="STOP_INSUFFICIENT_EVIDENCE",
                reason_codes=["PROVIDER_EVIDENCE_UNAVAILABLE"], evidence_refs=[],
                public_summary=(
                    loop.reflection.public_summary if loop.reflection else
                    "Thiếu bằng chứng từ nhà cung cấp nên chưa thể đề xuất hành trình mới."
                ),
                user_message="Chưa đủ dữ liệu nhà cung cấp để chứng minh một phương án an toàn.",
                limitations=["Provider failure is not an infeasibility verdict."],
                requires_owner_confirmation=False,
            )
            status = "INSUFFICIENT_EVIDENCE"
            reflection = ReflectionDecision(
                evidence_sufficient=False, hypothesis_status="UNCERTAIN",
                missing_evidence=["PROVIDER_EVIDENCE"],
                next_step="STOP_INSUFFICIENT_EVIDENCE", next_tool=None,
                reason_codes=["PROVIDER_EVIDENCE_UNAVAILABLE"], evidence_refs=[],
                public_summary=(
                    loop.reflection.public_summary if loop.reflection else
                    "Thiếu bằng chứng từ nhà cung cấp nên chưa thể đề xuất hành trình mới."
                ),
            )
        elif verdict == "SEARCH_EXHAUSTED":
            action = ActionProposalDraft(
                action="STOP_INSUFFICIENT_EVIDENCE",
                reason_codes=["SEARCH_EXHAUSTED"], evidence_refs=[],
                public_summary=(
                    loop.reflection.public_summary if loop.reflection else
                    "Đã hết phạm vi tìm kiếm nhưng chưa đủ bằng chứng để kết luận an toàn."
                ),
                user_message="Đã hết ngân sách tìm kiếm cho lần lập kế hoạch này.",
                limitations=["Search exhaustion is not an infeasibility verdict."],
                requires_owner_confirmation=False,
            )
            status = "SEARCH_EXHAUSTED"
            reflection = ReflectionDecision(
                evidence_sufficient=False, hypothesis_status="UNCERTAIN",
                missing_evidence=[], next_step="STOP_SEARCH_EXHAUSTED", next_tool=None,
                reason_codes=["SEARCH_EXHAUSTED"], evidence_refs=[],
                public_summary=(
                    loop.reflection.public_summary if loop.reflection else
                    "Đã hết phạm vi tìm kiếm nhưng chưa đủ bằng chứng để kết luận an toàn."
                ),
            )
        else:
            action = ActionProposalDraft(
                action="PROPOSE_REPLAN", reason_codes=["CANDIDATE_FEASIBLE"],
                evidence_refs=[], user_message="Có phương án mới cần bạn xác nhận.",
                limitations=[], requires_owner_confirmation=True,
            )
            status = "SUCCEEDED"
            reflection = ReflectionDecision(
                evidence_sufficient=True, hypothesis_status="SUPPORTED",
                missing_evidence=[], next_step="PROPOSE_ACTION", next_tool=None,
                reason_codes=["CANDIDATE_SAFETY_EVIDENCE_SUFFICIENT"], evidence_refs=[],
                public_summary=(
                    loop.reflection.public_summary if loop.reflection else
                    "Phương án mới đã đủ bằng chứng an toàn để chuyển sang bước xác nhận."
                ),
            )
            if candidate.get("plan_version") is not None:
                context_result.snapshot.pending_plan_version = int(candidate["plan_version"])
        deterministic_action = action
        try:
            drafted_action = self._supervisor.draft_action(
                feasibility_verdict=verdict or "INSUFFICIENT_EVIDENCE",
                observations=loop.observations,
                plan_diff=candidate.get("plan_diff"),
                operational_context={
                    "event_types": event_types,
                    "assessment": turn.assessment.model_dump(mode="json"),
                    "trip_context": context_result.snapshot.model_dump(mode="json"),
                    "telemetry": telemetry.model_dump(mode="json"),
                    "final_reflection": reflection.model_dump(mode="json"),
                },
            )
        except Exception:
            drafted_action = deterministic_action
        draft_guard = ActionGuard().validate(
            drafted_action,
            feasibility_verdict=verdict,
            station_unavailable_affects_remaining_trip=(
                loop.station_unavailable_affects_remaining_trip
                if "STATION_UNAVAILABLE" in event_types else None
            ),
            other_replan_event_active=any(
                event_type in {"ROUTE_DEVIATION", "SOC_UNDERPERFORMANCE"}
                for event_type in event_types
            ),
        )
        action = drafted_action if draft_guard.allowed else ConservativeSupervisor().draft_action(
            feasibility_verdict=verdict or "INSUFFICIENT_EVIDENCE",
            observations=loop.observations,
            plan_diff=candidate.get("plan_diff"),
        )
        loop.decision_trace.extend([
            DecisionTraceItem(
                sequence=len(loop.decision_trace) + 1,
                stage="PROPOSING_ACTION", summary_code="ACTION_DRAFTED",
                status="SUCCEEDED" if draft_guard.allowed else "BLOCKED",
                evidence_refs=action.evidence_refs,
                reason_codes=(
                    action.reason_codes if draft_guard.allowed
                    else [draft_guard.reason_code or "ACTION_GUARD_REJECTED"]
                ),
                response_source=action.response_source,
                public_summary=(
                    action.user_message if draft_guard.allowed
                    else "Đề xuất của trợ lý bị chặn và đã chuyển sang hành động thận trọng."
                ),
            ),
            DecisionTraceItem(
                sequence=len(loop.decision_trace) + 2,
                stage="GUARDING_ACTION", summary_code="ACTION_SAFETY_GUARD_PASSED",
                status="SUCCEEDED", evidence_refs=action.evidence_refs,
                reason_codes=action.reason_codes,
                public_summary=(
                    "ActionGuard đã kiểm tra đề xuất. Phương án đang chờ người dùng xác nhận."
                    if action.requires_owner_confirmation else
                    "ActionGuard đã kiểm tra và giữ hệ thống ở trạng thái an toàn."
                ),
            ),
        ])
        if self._on_trace is not None:
            self._on_trace(loop.decision_trace[-2])
            self._on_trace(loop.decision_trace[-1])
        guard = ActionGuard().validate(
            action,
            feasibility_verdict=verdict,
            station_unavailable_affects_remaining_trip=(
                loop.station_unavailable_affects_remaining_trip
                if "STATION_UNAVAILABLE" in event_types else None
            ),
            other_replan_event_active=any(
                event_type in {"ROUTE_DEVIATION", "SOC_UNDERPERFORMANCE"}
                for event_type in event_types
            ),
        )
        if not guard.allowed:
            raise ValueError(guard.reason_code)
        diff = candidate.get("plan_diff")
        return ReplanningOutcome(
            agent_run_id=str(uuid4()), status=status, epoch=coordination.epoch,
            context=context_result.snapshot, assessment=turn.assessment,
            action=action, candidate=candidate, created_at=now,
            tool_runs=tool_runs, decision_trace=loop.decision_trace,
            plan_diff_id=(str(uuid4()) if diff else None), plan_diff=diff,
            reflection=reflection,
        )
