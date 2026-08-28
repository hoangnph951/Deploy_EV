from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from src.packages.agent.replanning.schemas import (
    DecisionTraceItem,
    DiagnosticObservation,
    ReflectionDecision,
    SituationAssessment,
    ToolDecision,
)
from src.packages.contracts.monitoring import TelemetrySnapshot
from src.packages.contracts.replanning import TripContextSnapshot
from src.packages.core.replanning.application.diagnostics import (
    DiagnosticRegistry,
    required_diagnostics,
)


@dataclass
class LoopResult:
    candidate: dict | None = None
    observations: list[DiagnosticObservation] = field(default_factory=list)
    decision_trace: list[DecisionTraceItem] = field(default_factory=list)
    blocked: bool = False
    blocked_reason_codes: list[str] = field(default_factory=list)
    blocked_missing_evidence: list[str] = field(default_factory=list)
    blocked_summary: str = ""
    reflection: ReflectionDecision | None = None
    continue_current_plan: bool = False
    station_unavailable_affects_remaining_trip: bool | None = None


class SupervisorLoop:
    """Bounded public decision loop; it records evidence, never private reasoning."""

    def __init__(
        self, *, planner, supervisor, registry: DiagnosticRegistry | None = None,
        max_tools: int = 8, on_trace: Callable[[DecisionTraceItem], None] | None = None,
    ):
        self._planner = planner
        self._supervisor = supervisor
        self._registry = registry or DiagnosticRegistry()
        self._max_tools = max_tools
        self._on_trace = on_trace

    def _record(self, result: LoopResult, item: DecisionTraceItem) -> None:
        result.decision_trace.append(item)
        if self._on_trace is not None:
            self._on_trace(item)

    def run(
        self,
        *,
        event_types: list[str],
        context: TripContextSnapshot,
        telemetry: TelemetrySnapshot,
        assessment: SituationAssessment,
        initial_decision: ToolDecision,
    ) -> LoopResult:
        result = LoopResult()
        self._record(result, DecisionTraceItem(
            sequence=1, stage="ASSESSING", summary_code="SITUATION_ASSESSED",
            status="SUCCEEDED", reason_codes=context.unresolved_constraints.unresolved_reason_codes,
            public_summary=assessment.public_summary,
        ))
        pending = required_diagnostics(event_types)
        next_tool = self._validated_tool(initial_decision.tool_name, pending)
        if pending and next_tool is None:
            self._block(
                result,
                reason_code="AI_TOOL_SELECTION_INVALID",
                missing_evidence=["VALID_TOOL_SELECTION"],
                summary="Trợ lý chưa chọn được công cụ hợp lệ trong phạm vi cho phép.",
            )
            return result
        while pending:
            name = next_tool
            pending.remove(name)
            if len(result.observations) >= self._max_tools:
                self._block(
                    result,
                    reason_code="TOOL_BUDGET_EXHAUSTED",
                    missing_evidence=["REMAINING_DIAGNOSTICS"],
                    summary="Đã hết ngân sách công cụ trước khi thu thập đủ bằng chứng.",
                )
                break
            projection = None
            if name == "project_current_plan":
                projector = getattr(self._planner, "project_remaining_plan", None)
                if projector is not None:
                    projection = projector(
                        trip_id=context.trip_id,
                        base_plan_version=context.current_confirmed_plan_version,
                        traveled_distance_km=telemetry.distance_km,
                        excluded_station_ids=context.unresolved_constraints.excluded_station_ids,
                    )
            observation = self._registry.execute(
                name,
                context=context,
                telemetry=telemetry,
                current_plan_projection=projection,
            )
            result.observations.append(observation)
            self._record(result, DecisionTraceItem(
                sequence=len(result.decision_trace) + 1,
                stage="DIAGNOSING", summary_code="DIAGNOSTIC_COMPLETED",
                status=observation.status, tool=name,
                evidence_refs=observation.evidence_refs,
                reason_codes=observation.reason_codes,
                public_summary=observation.public_summary,
            ))
            reflection = self._supervisor.reflect(
                event_types=event_types,
                active_constraints=context.unresolved_constraints,
                observations=result.observations,
                allowed_tools=pending,
                context=context,
                telemetry=telemetry,
                assessment=assessment,
            )
            result.reflection = reflection
            self._record(result, DecisionTraceItem(
                sequence=len(result.decision_trace) + 1,
                stage="REFLECTING", summary_code=(
                    "EVIDENCE_ACCEPTED" if observation.status == "SUCCEEDED"
                    else "EVIDENCE_INSUFFICIENT"
                ),
                status=observation.status, tool=name,
                evidence_refs=reflection.evidence_refs or observation.evidence_refs,
                missing_evidence=reflection.missing_evidence,
                reason_codes=reflection.reason_codes or observation.reason_codes,
                public_summary=reflection.public_summary,
            ))
            if observation.status != "SUCCEEDED":
                self._block(
                    result,
                    reason_code=(observation.reason_codes[0] if observation.reason_codes else "TOOL_FAILED"),
                    missing_evidence=reflection.missing_evidence,
                    summary=reflection.public_summary,
                )
                return result
            if name == "project_current_plan":
                impact = observation.facts.get(
                    "station_unavailable_affects_remaining_trip"
                )
                if isinstance(impact, bool):
                    result.station_unavailable_affects_remaining_trip = impact
                station_only = set(event_types) == {"STATION_UNAVAILABLE"}
                if station_only and impact is False:
                    continuation_reflection = self._supervisor.reflect(
                        event_types=event_types,
                        active_constraints=context.unresolved_constraints,
                        observations=result.observations,
                        allowed_tools=[],
                        context=context,
                        telemetry=telemetry,
                        assessment=assessment,
                    )
                    self._record(result, DecisionTraceItem(
                        sequence=len(result.decision_trace) + 1,
                        stage="REFLECTING", summary_code="STATION_IMPACT_REVIEWED",
                        status="SUCCEEDED", tool="project_current_plan",
                        evidence_refs=continuation_reflection.evidence_refs,
                        missing_evidence=continuation_reflection.missing_evidence,
                        reason_codes=continuation_reflection.reason_codes,
                        public_summary=continuation_reflection.public_summary,
                    ))
                    if continuation_reflection.next_step != "PROPOSE_ACTION":
                        self._block(
                            result,
                            reason_code="AI_STATION_IMPACT_DECISION_INVALID",
                            missing_evidence=[],
                            summary=continuation_reflection.public_summary,
                        )
                        return result
                    result.reflection = continuation_reflection
                    result.continue_current_plan = True
                    return result
            if pending:
                next_tool = self._validated_tool(reflection.next_tool, pending)
                if reflection.next_step != "CALL_TOOL" or next_tool is None:
                    self._block(
                        result,
                        reason_code="AI_TOOL_SELECTION_INVALID",
                        missing_evidence=reflection.missing_evidence or ["VALID_TOOL_SELECTION"],
                        summary=reflection.public_summary,
                    )
                    return result

        if len(result.observations) >= self._max_tools:
            self._block(
                result,
                reason_code="TOOL_BUDGET_EXHAUSTED",
                missing_evidence=["F1_CANDIDATE"],
                summary="Đã hết ngân sách công cụ trước khi tạo phương án F1.",
            )
            return result
        projection_observation = next(
            (item for item in result.observations if item.tool == "project_current_plan"),
            None,
        )
        projection_facts = projection_observation.facts if projection_observation else {}
        station_impacted = (
            "STATION_UNAVAILABLE" in event_types
            and result.station_unavailable_affects_remaining_trip is True
        )
        build_tool = (
            "build_minimal_substitution" if station_impacted else "build_full_replan"
        )
        strategy_reflection = self._supervisor.reflect(
            event_types=event_types,
            active_constraints=context.unresolved_constraints,
            observations=result.observations,
            allowed_tools=[build_tool],
            context=context,
            telemetry=telemetry,
            assessment=assessment,
        )
        self._record(result, DecisionTraceItem(
            sequence=len(result.decision_trace) + 1,
            stage="REFLECTING", summary_code="REPLAN_STRATEGY_SELECTED",
            status="SUCCEEDED", tool=build_tool,
            evidence_refs=strategy_reflection.evidence_refs,
            missing_evidence=strategy_reflection.missing_evidence,
            reason_codes=strategy_reflection.reason_codes,
            public_summary=strategy_reflection.public_summary,
        ))
        if (
            strategy_reflection.next_step != "CALL_TOOL"
            or strategy_reflection.next_tool != build_tool
        ):
            self._block(
                result,
                reason_code="AI_REPLAN_STRATEGY_INVALID",
                missing_evidence=strategy_reflection.missing_evidence or ["VALID_REPLAN_STRATEGY"],
                summary=strategy_reflection.public_summary,
            )
            return result

        result.candidate = self._build_candidate(
            strategy=(
                "MINIMAL_SUBSTITUTION"
                if build_tool == "build_minimal_substitution"
                else "FULL_REPLAN"
            ),
            context=context,
            projection_facts=projection_facts,
        )
        self._record_candidate(result, build_tool, context)

        if (
            build_tool == "build_minimal_substitution"
            and result.candidate.get("feasibility_verdict") == "STRATEGY_NOT_SATISFIED"
        ):
            fallback_reflection = self._supervisor.reflect(
                event_types=event_types,
                active_constraints=context.unresolved_constraints,
                observations=result.observations,
                allowed_tools=["build_full_replan"],
                context=context,
                telemetry=telemetry,
                assessment=assessment,
            )
            self._record(result, DecisionTraceItem(
                sequence=len(result.decision_trace) + 1,
                stage="REFLECTING", summary_code="MINIMAL_SUBSTITUTION_REVIEWED",
                status="SUCCEEDED", tool="build_minimal_substitution",
                evidence_refs=fallback_reflection.evidence_refs,
                missing_evidence=fallback_reflection.missing_evidence,
                reason_codes=fallback_reflection.reason_codes,
                public_summary=fallback_reflection.public_summary,
            ))
            if (
                fallback_reflection.next_step != "CALL_TOOL"
                or fallback_reflection.next_tool != "build_full_replan"
            ):
                self._block(
                    result,
                    reason_code="AI_FULL_REPLAN_FALLBACK_INVALID",
                    missing_evidence=["FULL_REPLAN_STRATEGY"],
                    summary=fallback_reflection.public_summary,
                )
                return result
            result.candidate = self._build_candidate(
                strategy="FULL_REPLAN",
                context=context,
                projection_facts=projection_facts,
            )
            self._record_candidate(result, "build_full_replan", context)

        candidate_observation = result.observations[-1]
        candidate_reflection = self._supervisor.reflect(
            event_types=event_types,
            active_constraints=context.unresolved_constraints,
            observations=result.observations,
            allowed_tools=["compare_plans"],
            context=context,
            telemetry=telemetry,
            assessment=assessment,
        )
        self._record(result, DecisionTraceItem(
            sequence=len(result.decision_trace) + 1,
            stage="REFLECTING", summary_code="CANDIDATE_FEASIBILITY_REVIEWED",
            status="SUCCEEDED", tool=candidate_observation.tool,
            evidence_refs=candidate_reflection.evidence_refs or candidate_observation.evidence_refs,
            missing_evidence=candidate_reflection.missing_evidence,
            reason_codes=candidate_reflection.reason_codes or candidate_observation.reason_codes,
            public_summary=candidate_reflection.public_summary,
        ))
        if (
            candidate_reflection.next_step != "CALL_TOOL"
            or candidate_reflection.next_tool != "compare_plans"
        ):
            self._block(
                result,
                reason_code="AI_TOOL_SELECTION_INVALID",
                missing_evidence=candidate_reflection.missing_evidence or ["PLAN_COMPARISON"],
                summary=candidate_reflection.public_summary,
            )
            return result
        comparison = DiagnosticObservation(
            tool="compare_plans", status="SUCCEEDED", provider="F4_PLAN_DIFF_ENGINE",
            freshness="NOT_APPLICABLE",
            facts={"plan_diff_available": bool(result.candidate.get("plan_diff"))},
            evidence_refs=[], reason_codes=["PLAN_COMPARISON_COMPLETED"],
            public_summary=_comparison_summary(result.candidate),
        )
        result.observations.append(comparison)
        self._record(result, DecisionTraceItem(
            sequence=len(result.decision_trace) + 1,
            stage="COMPARING_PLANS", summary_code="PLANS_COMPARED",
            status="SUCCEEDED", tool="compare_plans",
            reason_codes=comparison.reason_codes,
            public_summary=comparison.public_summary,
        ))
        result.reflection = self._supervisor.reflect(
            event_types=event_types,
            active_constraints=context.unresolved_constraints,
            observations=result.observations,
            allowed_tools=[],
            context=context,
            telemetry=telemetry,
            assessment=assessment,
        )
        self._record(result, DecisionTraceItem(
            sequence=len(result.decision_trace) + 1,
            stage="REFLECTING", summary_code="COMPARISON_REVIEWED",
            status="SUCCEEDED", tool="compare_plans",
            evidence_refs=result.reflection.evidence_refs,
            missing_evidence=result.reflection.missing_evidence,
            reason_codes=result.reflection.reason_codes or comparison.reason_codes,
            public_summary=result.reflection.public_summary,
        ))
        return result

    def _build_candidate(
        self, *, strategy: str, context: TripContextSnapshot, projection_facts: dict
    ) -> dict:
        return self._planner.build_candidate(
            trip_id=context.trip_id,
            current_lat=context.current_lat,
            current_lon=context.current_lng,
            current_soc_percent=context.current_soc_percent,
            base_plan_version=context.current_confirmed_plan_version,
            context_version=context.context_version,
            excluded_station_ids=context.unresolved_constraints.excluded_station_ids,
            remaining_station_ids=projection_facts.get("remaining_station_ids", []),
            original_station_ids=projection_facts.get("original_station_ids", []),
            unaffected_remaining_station_ids=projection_facts.get(
                "unaffected_remaining_station_ids", []
            ),
            current_plan_projection=projection_facts,
            strategy=strategy,
        )

    def _record_candidate(
        self, result: LoopResult, tool_name: str, context: TripContextSnapshot
    ) -> None:
        observation = DiagnosticObservation(
            tool=tool_name, status="SUCCEEDED",
            provider="F1_PLANNING_ORCHESTRATOR", freshness="FRESH",
            facts=_candidate_facts(result.candidate or {}),
            evidence_refs=[f"telemetry:{context.telemetry_snapshot_id}"],
            reason_codes=[
                "MINIMAL_SUBSTITUTION_NOT_SATISFIED"
                if (result.candidate or {}).get("feasibility_verdict")
                == "STRATEGY_NOT_SATISFIED"
                else "DETERMINISTIC_FEASIBILITY"
            ],
            public_summary=_candidate_summary(result.candidate or {}),
        )
        result.observations.append(observation)
        self._record(result, DecisionTraceItem(
            sequence=len(result.decision_trace) + 1,
            stage="BUILDING_CANDIDATE", summary_code=(
                "MINIMAL_SUBSTITUTION_ATTEMPTED"
                if tool_name == "build_minimal_substitution"
                else "FULL_REPLAN_BUILT"
            ),
            status="SUCCEEDED", tool=tool_name,
            evidence_refs=observation.evidence_refs,
            reason_codes=observation.reason_codes,
            public_summary=observation.public_summary,
        ))

    @staticmethod
    def _validated_tool(selected_tool: str | None, allowed_tools: list[str]) -> str | None:
        """Validate the model's choice without making a replacement decision locally."""
        return selected_tool if selected_tool in allowed_tools else None

    @staticmethod
    def _block(
        result: LoopResult,
        *,
        reason_code: str,
        missing_evidence: list[str],
        summary: str,
    ) -> None:
        result.blocked = True
        result.blocked_reason_codes = [reason_code]
        result.blocked_missing_evidence = missing_evidence
        result.blocked_summary = summary


def _candidate_facts(candidate: dict) -> dict[str, object]:
    outcome = candidate.get("outcome") or {}
    plan = outcome.get("plan") or {}
    stops = plan.get("charging_stops") or []
    return {
        "feasibility_verdict": candidate.get("feasibility_verdict"),
        "plan_version": candidate.get("plan_version"),
        "distance_km": (plan.get("route") or {}).get("distance_km"),
        "final_soc_percent": plan.get("final_arrival_soc_percent"),
        "charging_station_ids": [stop.get("station_id") for stop in stops if stop.get("station_id")],
        "charging_station_names": [stop.get("name") for stop in stops if stop.get("name")],
    }


def _candidate_summary(candidate: dict) -> str:
    facts = _candidate_facts(candidate)
    verdict = facts["feasibility_verdict"]
    names = facts["charging_station_names"]
    if verdict == "FEASIBLE":
        station_text = f" qua {', '.join(names)}" if names else " không cần dừng sạc"
        return f"F1 đã tạo phương án khả thi{station_text}; SOC và tuyến đã được kiểm tra."
    if verdict == "INFEASIBLE":
        return "F1 không chứng minh được phương án mới đáp ứng mức pin dự phòng."
    if verdict == "STRATEGY_NOT_SATISFIED":
        return "F1 chưa tìm được phương án chỉ thay đổi tối thiểu; cần mở rộng sang lập lại toàn bộ."
    return "F1 chưa cung cấp đủ bằng chứng để kết luận phương án mới an toàn."


def _comparison_summary(candidate: dict) -> str:
    diff = candidate.get("plan_diff") or {}
    if not diff:
        return "Đã kiểm tra phương án mới; chưa có chênh lệch định lượng để hiển thị."
    return (
        "Đã so sánh lộ trình hiện tại và phương án mới về quãng đường, thời gian, "
        "SOC đích và biên dự phòng."
    )
