from __future__ import annotations

from uuid import uuid4

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, Field

from src.apps.api.bootstrap.config import get_settings
from src.packages.contracts.monitoring import MonitoringEvent, TelemetrySnapshot
from src.packages.contracts.replanning import (
    AgentDecision,
    CandidatePlanSummary,
    PlanDiff,
)
from src.packages.core.simulator.application.catalog_service import BaseSimulationSnapshot


class AiToolSelection(BaseModel):
    intent: str
    strategy: str
    confidence: float = Field(ge=0, le=1)
    selected_tools: list[str] = Field(min_length=1, max_length=6)
    rationale: str = Field(min_length=1, max_length=1000)


_ALLOWED_TOOLS = {
    "ROUTE_RECOVERY": {"route_from_current_position", "station_search", "energy_simulation", "feasibility_check", "compare_plans"},
    "ENERGY_RESCUE": {"nearest_station_reachability", "station_search", "energy_simulation", "feasibility_check", "compare_plans"},
    "STATION_SUBSTITUTION": {"station_search", "energy_simulation", "feasibility_check", "compare_plans"},
    "TELEMETRY_RECOVERY": {"request_telemetry_refresh"},
}

_EVENT_INTENT = {
    "ROUTE_DEVIATION": "ROUTE_RECOVERY",
    "SOC_UNDERPERFORMANCE": "ENERGY_RESCUE",
    "STATION_UNAVAILABLE": "STATION_SUBSTITUTION",
    "STALE_TELEMETRY": "TELEMETRY_RECOVERY",
}


class ReplanningSupervisor:
    """AI-assisted F4 supervisor with a deterministic safety fallback.

    It exposes the complete intent/tool/diff/action trace for demo replay.
    The model may classify intent and select tools, but it cannot change
    deterministic evidence or action guards.
    """

    def __init__(self, *, client: OpenAI | None = None):
        settings = get_settings()
        self._model = settings.openai_replanning_model
        self._client = client
        if self._client is None and settings.app_env != "test":
            if not settings.openai_replanning_enabled:
                raise RuntimeError("OpenAI replanning decision support is disabled.")
            if not settings.openai_api_key.strip():
                raise RuntimeError(
                    "OPENAI_API_KEY is required for simulator agent decisions."
                )
            self._client = OpenAI(
                api_key=settings.openai_api_key.strip(),
                base_url=settings.openai_base_url or None,
                timeout=settings.openai_replanning_timeout_seconds,
                max_retries=0,
            )

    def decide(
        self,
        *,
        snapshot: BaseSimulationSnapshot,
        telemetry: TelemetrySnapshot,
        events: list[MonitoringEvent],
        profile: str,
    ) -> AgentDecision:
        event_types = {item.event_type for item in events}
        evidence = [telemetry.event_id, *[item.event_id for item in events]]
        if "STALE_TELEMETRY" in event_types:
            decision = AgentDecision(
                agent_run_id=str(uuid4()),
                intent="TELEMETRY_RECOVERY",
                intent_confidence=1.0,
                classification_source="DETERMINISTIC_FALLBACK",
                strategy="WAIT_FOR_FRESH_SAMPLE",
                selected_tools=["request_telemetry_refresh"],
                events=events,
                action="REQUEST_NEW_TELEMETRY",
                action_guard="PASSED",
                requires_owner_confirmation=False,
                reason_codes=["TELEMETRY_TOO_OLD"],
                evidence_refs=evidence,
                explanation="Telemetry đã quá 60 giây; Agent dừng planning và yêu cầu một sample mới.",
            )
            return self._apply_ai_selection(decision, snapshot=snapshot, telemetry=telemetry, events=events, profile=profile)

        if profile == "NO_FEASIBLE_ALTERNATIVE":
            decision = AgentDecision(
                agent_run_id=str(uuid4()),
                intent="ENERGY_RESCUE",
                intent_confidence=1.0,
                classification_source="DETERMINISTIC_FALLBACK",
                strategy="CHECK_NEAREST_THEN_EXPAND",
                selected_tools=[
                    "nearest_station_reachability",
                    "station_search",
                    "energy_simulation",
                    "feasibility_check",
                ],
                events=events,
                action="PROPOSE_REPLAN",
                action_guard="PASSED",
                requires_owner_confirmation=True,
                reason_codes=["ALL_ALTERNATIVE_STATIONS_UNAVAILABLE", "NO_FEASIBLE_CANDIDATE"],
                evidence_refs=evidence,
                explanation="Agent nhận diện không còn phương án trong snapshot hiện tại và đề xuất gọi recovery search để tìm thêm trạm có thể dùng.",
                limitations=["Cần chạy lại F1 với dữ liệu trạm hiện tại; chưa tự động áp dụng kế hoạch."],
                plan_diff=PlanDiff(
                    old_safety="INFEASIBLE",
                    candidate_safety="INFEASIBLE",
                    summary="Không có candidate plan đạt reserve SOC.",
                ),
            )
            return self._apply_ai_selection(decision, snapshot=snapshot, telemetry=telemetry, events=events, profile=profile)

        if "SOC_UNDERPERFORMANCE" in event_types:
            intent = "ENERGY_RESCUE"
            strategy = "CHECK_NEAREST_THEN_EXPAND"
            tools = [
                "nearest_station_reachability",
                "station_search",
                "energy_simulation",
                "feasibility_check",
                "compare_plans",
            ]
            reason_codes = ["ACTUAL_SOC_BELOW_EXPECTED", "NEAREST_STATION_REACHABILITY_CHECKED"]
        elif "STATION_UNAVAILABLE" in event_types:
            intent = "STATION_SUBSTITUTION"
            strategy = "EXCLUDE_AND_MINIMIZE_CHANGE"
            tools = ["station_search", "energy_simulation", "feasibility_check", "compare_plans"]
            reason_codes = ["PLANNED_STATION_EXCLUDED"]
        else:
            intent = "ROUTE_RECOVERY"
            strategy = "REPLAN_FROM_CURRENT_POSITION"
            tools = ["route_from_current_position", "energy_simulation", "feasibility_check", "compare_plans"]
            reason_codes = ["VEHICLE_OFF_CONFIRMED_ROUTE"]

        all_stations = [str(item.get("station_id")) for item in snapshot.charging_stops if item.get("station_id")]
        removed = [item.station_id for item in events if item.station_id]
        remaining_stations = [item for item in all_stations if item not in removed]
        if "STATION_UNAVAILABLE" in event_types:
            decision = AgentDecision(
                agent_run_id=str(uuid4()),
                intent=intent,
                intent_confidence=1.0,
                classification_source="DETERMINISTIC_FALLBACK",
                strategy=strategy,
                selected_tools=tools,
                events=events,
                action="PROPOSE_REPLAN",
                action_guard="PASSED",
                requires_owner_confirmation=True,
                reason_codes=reason_codes,
                evidence_refs=evidence,
                explanation=(
                    "Trạm kế tiếp không khả dụng. Agent đã khóa trạm này và chờ người dùng "
                    "cho phép gọi F1 realtime để tìm, kiểm tra và so sánh trạm thay thế."
                ),
                limitations=["Chưa có candidate trước khi người dùng bấm Lập lại kế hoạch."],
                plan_diff=PlanDiff(
                    removed_station_ids=removed,
                    old_safety="DEGRADED",
                    candidate_safety="PENDING_F1_REALTIME",
                    summary="Đã loại trạm lỗi; candidate và trạm thay thế đang chờ F1 realtime.",
                ),
            )
            return self._apply_ai_selection(decision, snapshot=snapshot, telemetry=telemetry, events=events, profile=profile)

        remaining_ratio = max(0.0, 1.0 - telemetry.progress_percent / 100)
        old_distance = float(snapshot.route.get("distance_km") or 0) * remaining_ratio
        candidate_distance = old_distance + (2.5 if intent == "ROUTE_RECOVERY" else 0.8)
        old_duration = float(snapshot.route.get("duration_min") or 0) * remaining_ratio
        candidate_duration = old_duration + (4.0 if intent == "ROUTE_RECOVERY" else 2.0)
        final_soc = max(15.0, float(snapshot.energy.get("final_arrival_soc_percent") or telemetry.actual_soc_percent))
        diff = PlanDiff(
            distance_delta_km=round(candidate_distance - old_distance, 2),
            duration_delta_min=round(candidate_duration - old_duration, 2),
            final_soc_delta_percent=round(final_soc - float(snapshot.energy.get("final_arrival_soc_percent") or final_soc), 2),
            removed_station_ids=removed,
            old_safety="DEGRADED",
            candidate_safety="FEASIBLE",
            summary="Candidate dùng cùng telemetry snapshot và đã vượt action guard của demo.",
        )
        candidate = CandidatePlanSummary(
            candidate_id=str(uuid4()),
            origin_lat=telemetry.lat,
            origin_lng=telemetry.lng,
            destination_lat=snapshot.destination_lat,
            destination_lng=snapshot.destination_lng,
            distance_km=round(candidate_distance, 2),
            duration_min=round(candidate_duration, 2),
            final_soc_percent=round(final_soc, 2),
            station_ids=remaining_stations,
            safety_verdict="FEASIBLE",
        )
        decision = AgentDecision(
            agent_run_id=str(uuid4()),
            intent=intent,
            intent_confidence=1.0,
            classification_source="DETERMINISTIC_FALLBACK",
            strategy=strategy,
            selected_tools=tools,
            events=events,
            action="PROPOSE_REPLAN",
            action_guard="PASSED",
            requires_owner_confirmation=True,
            reason_codes=reason_codes,
            evidence_refs=evidence,
            explanation=f"Agent chọn {strategy}, dùng telemetry hiện tại và so sánh phần plan còn lại trước khi đề xuất.",
            limitations=["Candidate dành cho simulation demo; không tự động thay thế plan F2 đã confirm."],
            plan_diff=diff,
            candidate_plan=candidate,
        )
        return self._apply_ai_selection(decision, snapshot=snapshot, telemetry=telemetry, events=events, profile=profile)

    def _apply_ai_selection(
        self,
        decision: AgentDecision,
        *,
        snapshot: BaseSimulationSnapshot,
        telemetry: TelemetrySnapshot,
        events: list[MonitoringEvent],
        profile: str,
    ) -> AgentDecision:
        """Let AI choose only an event-approved tool sequence; safety stays deterministic."""
        if self._client is None:
            return decision
        event_types = [event.event_type for event in events]
        facts = {
            "profile": profile,
            "events": event_types,
            "telemetry": {
                "actual_soc_percent": telemetry.actual_soc_percent,
                "expected_soc_percent": telemetry.expected_soc_percent,
                "progress_percent": telemetry.progress_percent,
                "distance_to_route_km": telemetry.distance_to_route_km,
            },
            "planned_station_ids": [str(stop.get("station_id")) for stop in snapshot.charging_stops],
            "allowed_tools_by_intent": _ALLOWED_TOOLS,
        }
        prompt = (
            "You are AI Agent 1 for an EV trip recovery workflow. Classify the incident and select "
            "the smallest useful sequence of tools from the supplied allowlist. For "
            "NO_FEASIBLE_ALTERNATIVE, prefer nearest_station_reachability then station_search so "
            "the system can discover other stations. Never claim a route or station is safe; "
            "feasibility_check is the deterministic safety authority. Return a confidence between "
            "0 and 1 and JSON only.\n"
            f"Facts: {facts}"
        )
        try:
            result = self._client.responses.parse(
                model=self._model,
                input=prompt,
                text_format=AiToolSelection,
                max_output_tokens=500,
            ).output_parsed
        except (OpenAIError, TypeError, ValueError):
            return decision
        if not isinstance(result, AiToolSelection):
            return decision
        if result.confidence < 0.80:
            return decision
        expected_intents = {_EVENT_INTENT[event.event_type] for event in events if event.event_type in _EVENT_INTENT}
        if result.intent not in expected_intents:
            return decision
        allowed = _ALLOWED_TOOLS.get(result.intent, set())
        if not allowed or any(tool not in allowed for tool in result.selected_tools):
            return decision
        if result.intent == "ROUTE_RECOVERY" and "route_from_current_position" not in result.selected_tools:
            return decision
        if result.intent == "ENERGY_RESCUE":
            required_prefix = ["nearest_station_reachability"]
            if result.selected_tools[:1] != required_prefix or "feasibility_check" not in result.selected_tools:
                return decision
            if "station_search" not in result.selected_tools:
                return decision
        if profile == "NO_FEASIBLE_ALTERNATIVE" and "station_search" not in result.selected_tools:
            return decision
        decision.intent = result.intent if result.intent in _ALLOWED_TOOLS else decision.intent
        decision.strategy = result.strategy
        decision.selected_tools = result.selected_tools
        decision.intent_confidence = result.confidence
        decision.classification_source = "AI_AGENT"
        decision.explanation = f"AI Agent 1: {result.rationale} Safety engine vẫn phải xác minh feasibility trước khi đề xuất áp dụng."
        return decision
