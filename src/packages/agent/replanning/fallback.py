from __future__ import annotations

from dataclasses import dataclass

from src.packages.agent.replanning.schemas import (
    ActionProposalDraft,
    DiagnosticObservation,
    ReflectionDecision,
    SituationAssessment,
    ToolDecision,
)
from src.packages.contracts.replanning import ActiveConstraintContext


@dataclass(frozen=True)
class SupervisorTurn:
    assessment: SituationAssessment
    decision: ToolDecision
    action: ActionProposalDraft | None = None


class ConservativeSupervisor:
    """Schema-compatible safe behavior when OpenAI cannot be used."""

    def assess(
        self, *, event_types: list[str], active_constraints: ActiveConstraintContext,
        allowed_tools: list[str] | None = None, context=None, telemetry=None,
    ) -> SupervisorTurn:
        allowed_tools = allowed_tools or []
        if active_constraints.telemetry_blocked or "STALE_TELEMETRY" in event_types:
            action = ActionProposalDraft(
                action="REQUEST_NEW_TELEMETRY",
                reason_codes=["TELEMETRY_BLOCKED"],
                evidence_refs=[],
                user_message="Cần telemetry GPS và SOC mới trước khi lập lại kế hoạch.",
                limitations=["Không sử dụng vị trí hoặc SOC đã cũ để tính tuyến."],
                requires_owner_confirmation=False,
            )
            return SupervisorTurn(
                SituationAssessment(
                    primary_objective="RECOVER_TELEMETRY", urgency="HIGH",
                    strategy="Fail closed and request fresh safety evidence.",
                    known_facts=event_types, constraints=["TELEMETRY_BLOCKED"],
                    missing_evidence=["FRESH_GPS", "FRESH_SOC"],
                    reason_codes=["TELEMETRY_BLOCKED"], confidence=1.0,
                    public_summary=(
                        "GPS hoặc mức pin đã cũ. Dừng lập lại kế hoạch và yêu cầu dữ liệu xe mới."
                    ),
                ),
                ToolDecision(
                    decision="CALL_TOOL" if allowed_tools else "PROPOSE_ACTION",
                    tool_name=allowed_tools[0] if allowed_tools else None,
                    expected_evidence=["FRESH_TELEMETRY"] if allowed_tools else [],
                    reason_codes=["TELEMETRY_BLOCKED"],
                ),
                action,
            )
        composite = len(set(event_types)) > 1
        objective = "COMPOSITE_RECOVERY" if composite else {
            "ROUTE_DEVIATION": "RESTORE_SAFE_ROUTE",
            "SOC_UNDERPERFORMANCE": "PROTECT_RESERVE_SOC",
            "STATION_UNAVAILABLE": "REPLACE_UNAVAILABLE_STATION",
        }.get(event_types[0] if event_types else "", "PRESERVE_CURRENT_PLAN")
        strategy = (
            "MINIMAL_SUBSTITUTION_THEN_FULL_REPLAN"
            if "STATION_UNAVAILABLE" in event_types
            else "BUILD_F1_CANDIDATE_FROM_CURRENT_TELEMETRY"
        )
        return SupervisorTurn(
            SituationAssessment(
                primary_objective=objective, urgency="HIGH",
                strategy=strategy,
                known_facts=event_types,
                constraints=active_constraints.unresolved_reason_codes,
                missing_evidence=[], reason_codes=["SAFE_FALLBACK"], confidence=0.8,
                public_summary=(
                    "Ưu tiên bảo vệ mức pin dự phòng và thu thập đủ bằng chứng trước khi tạo phương án mới."
                    if objective == "PROTECT_RESERVE_SOC"
                    else "Thu thập bằng chứng tất định trước khi đề xuất thay đổi hành trình."
                ),
            ),
            ToolDecision(
                decision="CALL_TOOL",
                tool_name=allowed_tools[0] if allowed_tools else "build_candidate",
                arguments={"excluded_station_ids": active_constraints.excluded_station_ids},
                expected_evidence=["F1_FEASIBILITY_VERDICT"],
                reason_codes=["SAFE_FALLBACK"],
            ),
        )

    def reflect(
        self,
        *,
        event_types: list[str],
        active_constraints: ActiveConstraintContext,
        observations: list[DiagnosticObservation],
        allowed_tools: list[str],
        context=None,
        telemetry=None,
        assessment=None,
    ) -> ReflectionDecision:
        blocked = next((item for item in observations if item.status != "SUCCEEDED"), None)
        if blocked is not None or active_constraints.telemetry_blocked:
            return ReflectionDecision(
                evidence_sufficient=False, hypothesis_status="UNCERTAIN",
                missing_evidence=["FRESH_TELEMETRY"],
                next_step="REQUEST_TELEMETRY", next_tool=None,
                reason_codes=["TELEMETRY_BLOCKED"],
                evidence_refs=blocked.evidence_refs if blocked else [],
                public_summary=(
                    "Bằng chứng hiện tại không hợp lệ; cần GPS và mức pin mới trước khi tiếp tục."
                ),
            )
        if allowed_tools:
            return ReflectionDecision(
                evidence_sufficient=False, hypothesis_status="UNCERTAIN",
                missing_evidence=[], next_step="CALL_TOOL", next_tool=allowed_tools[0],
                reason_codes=["SAFE_FALLBACK_DIAGNOSTIC"],
                evidence_refs=[ref for item in observations for ref in item.evidence_refs],
                public_summary=_fallback_reflection_summary(
                    event_types, observations, allowed_tools[0]
                ),
            )
        return ReflectionDecision(
            evidence_sufficient=True, hypothesis_status="SUPPORTED",
            missing_evidence=[], next_step="PROPOSE_ACTION", next_tool=None,
            reason_codes=["SAFE_FALLBACK_EVIDENCE_COMPLETE"],
            evidence_refs=[ref for item in observations for ref in item.evidence_refs],
            public_summary=(
                "Đã có đủ bằng chứng công khai để chuyển sang tạo và kiểm tra phương án mới."
            ),
        )

    def draft_action(
        self,
        *,
        feasibility_verdict: str,
        observations: list[DiagnosticObservation],
        plan_diff: dict | None,
        operational_context: dict | None = None,
    ) -> ActionProposalDraft:
        evidence_refs = [ref for item in observations for ref in item.evidence_refs]
        if feasibility_verdict == "CURRENT_PLAN_UNAFFECTED":
            return ActionProposalDraft(
                action="CONTINUE_CURRENT_PLAN",
                reason_codes=["UNAVAILABLE_STATION_NOT_IN_REMAINING_TRIP"],
                evidence_refs=evidence_refs,
                user_message="Trạm không khả dụng không còn ảnh hưởng phần hành trình phía trước; tiếp tục kế hoạch hiện tại.",
                limitations=[], requires_owner_confirmation=False,
            )
        if feasibility_verdict == "INFEASIBLE":
            return ActionProposalDraft(
                action="NO_FEASIBLE_PLAN_REQUEST_ASSISTANCE",
                reason_codes=["DETERMINISTIC_INFEASIBLE"], evidence_refs=evidence_refs,
                user_message="Không tìm thấy phương án đã được chứng minh an toàn.",
                limitations=[], requires_owner_confirmation=False,
            )
        if feasibility_verdict in {"INSUFFICIENT_EVIDENCE", "SEARCH_EXHAUSTED"}:
            return ActionProposalDraft(
                action="STOP_INSUFFICIENT_EVIDENCE",
                reason_codes=[feasibility_verdict], evidence_refs=evidence_refs,
                user_message="Chưa đủ bằng chứng để đề xuất một hành trình an toàn.",
                limitations=[], requires_owner_confirmation=False,
            )
        return ActionProposalDraft(
            action="PROPOSE_REPLAN", reason_codes=["CANDIDATE_FEASIBLE"],
            evidence_refs=evidence_refs,
            user_message="Có phương án mới cần bạn xem xét và xác nhận.",
            limitations=[], requires_owner_confirmation=True,
        )


def _fallback_reflection_summary(
    event_types: list[str], observations: list[DiagnosticObservation], next_tool: str
) -> str:
    last_tool = observations[-1].tool if observations else ""
    if "SOC_UNDERPERFORMANCE" in event_types:
        if last_tool == "project_current_plan":
            return "Phần hành trình còn lại cần được kiểm tra lại theo SOC thực tế."
        if last_tool == "inspect_energy":
            return (
                "Mức pin dự phòng có rủi ro; tiếp tục kiểm tra lựa chọn sạc gần nhất."
            )
        if last_tool == "nearest_station_reachability":
            return (
                "Đã có phạm vi tìm trạm thay thế; có thể thử tạo phương án mới bằng F1."
            )
    return f"Bằng chứng hiện tại chưa đủ; tiếp tục với bước {next_tool}."
