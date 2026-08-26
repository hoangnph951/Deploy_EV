from __future__ import annotations

import json
import re
from math import isclose

from langchain_openai import ChatOpenAI

from src.apps.api.bootstrap.config import get_settings
from src.packages.contracts.trips import (
    ExplanationPayload,
    ExplanationReference,
    PlanProposal,
)
from src.packages.core.trips.infrastructure.station_service import CandidateStation

_NUMBER_RE = re.compile(r"(?<![\w-])-?\d+(?:[.,]\d+)?")
_QUOTED_RE = re.compile(r"['\"]([^'\"]{2,120})['\"]")


class DeterministicExplanationFallback:
    def generate(self, plan: PlanProposal, candidates: list[CandidateStation]) -> ExplanationPayload:
        return deterministic_explanation(plan, candidates)


class GroundingValidator:
    def validate(
        self,
        explanation: ExplanationPayload,
        plan: PlanProposal,
        candidates: list[CandidateStation],
    ) -> bool:
        return validate_grounded_explanation(explanation, plan, candidates)


def build_grounded_explanation(
    plan: PlanProposal,
    candidates: list[CandidateStation],
) -> ExplanationPayload:
    fallback = deterministic_explanation(plan, candidates)
    settings = get_settings()
    if settings.app_env == "test" or not settings.ai_plan_explanation_enabled or not settings.openai_api_key:
        return fallback

    facts = _fact_payload(plan, candidates)
    prompt = (
        "Ban chi duoc dien dat lai JSON su kien EV da duoc xac minh ben duoi. "
        "Khong them ten tram, so lieu, nguong hay ket luan moi. Giu nguyen cac key station_id "
        "va references. Tra ve ExplanationPayload bang tieng Viet.\n"
        f"{json.dumps(facts, ensure_ascii=False, default=str)}"
    )
    try:
        result = (
            ChatOpenAI(
                model=settings.model_name,
                api_key=settings.openai_api_key,
                temperature=0.0,
                timeout=min(3.0, settings.ai_plan_explanation_timeout_seconds),
                max_retries=0,
            )
            .with_structured_output(ExplanationPayload)
            .invoke(prompt)
        )
    except Exception:
        return fallback
    if not validate_grounded_explanation(result, plan, candidates):
        return fallback
    return result


def deterministic_explanation(
    plan: PlanProposal,
    candidates: list[CandidateStation],
) -> ExplanationPayload:
    reserve = plan.assumptions.reserve_soc_percent
    selected_ids = {stop.station_id for stop in plan.charging_stops}
    selected_reasons: dict[str, str] = {}
    rejected_reasons: dict[str, str] = {}
    references = [
        ExplanationReference(
            entity_type="ROUTE",
            entity_id=plan.plan_id,
            metric_name="DISTANCE_KM",
            metric_value=round(plan.route.distance_km, 2),
        ),
        ExplanationReference(
            entity_type="ROUTE",
            entity_id=plan.plan_id,
            metric_name="DETOUR_KM",
            metric_value=round(plan.route.detour_distance_km, 2),
        ),
        ExplanationReference(
            entity_type="ENERGY",
            entity_id=plan.plan_id,
            metric_name="FINAL_SOC_PERCENT",
            metric_value=round(plan.final_arrival_soc_percent, 2),
        ),
        ExplanationReference(
            entity_type="ENERGY",
            entity_id=plan.plan_id,
            metric_name="RESERVE_SOC_PERCENT",
            metric_value=round(reserve, 2),
        ),
    ]
    for stop in plan.charging_stops:
        selected_reasons[stop.station_id] = (
            f"Được chọn trong chuỗi đã qua Safety Gate: đến trạm còn "
            f"{stop.arrival_soc_percent:.1f}% SOC, công suất tối đa {stop.max_power_kw:.0f} kW "
            f"và detour {stop.detour_distance_km:.1f} km."
        )
        references.extend(
            [
                ExplanationReference(entity_type="STATION", entity_id=stop.station_id, metric_name="ARRIVAL_SOC", metric_value=round(stop.arrival_soc_percent, 2)),
                ExplanationReference(entity_type="STATION", entity_id=stop.station_id, metric_name="POWER_KW", metric_value=round(stop.max_power_kw, 2)),
                ExplanationReference(entity_type="STATION", entity_id=stop.station_id, metric_name="DETOUR_KM", metric_value=round(stop.detour_distance_km, 2)),
            ]
        )

    required_connector = (
        plan.assumptions.vehicle_profile.connector_type
        if plan.assumptions.vehicle_profile is not None
        else None
    )
    for station in candidates:
        if station.station_id in selected_ids:
            continue
        if required_connector and required_connector.upper() not in {item.upper() for item in station.connector_types}:
            reason = f"Bị loại vì không có đầu nối {required_connector} theo vehicle profile."
        elif station.freshness == "STALE":
            reason = "Bị loại vì dữ liệu trạm đã cũ và chưa đủ độ tin cậy cho Safety Gate."
        elif station.station_status != "ACTIVE":
            reason = f"Bị loại vì trạng thái trạm là {station.station_status}, không phải ACTIVE."
        else:
            reason = (
                "Không thuộc chuỗi trạm được Safety Gate xác minh cho phương án này; "
                f"dữ liệu ứng viên ghi nhận công suất {station.max_power_kw:.0f} kW và "
                f"detour {station.detour_distance_km:.1f} km."
            )
        rejected_reasons[station.station_id] = reason
        references.extend(
            [
                ExplanationReference(entity_type="STATION", entity_id=station.station_id, metric_name="POWER_KW", metric_value=round(station.max_power_kw, 2)),
                ExplanationReference(entity_type="STATION", entity_id=station.station_id, metric_name="DETOUR_KM", metric_value=round(station.detour_distance_km, 2)),
            ]
        )

    if plan.charging_stops:
        summary = (
            f"Phương án dùng {len(plan.charging_stops)} điểm sạc đã được kiểm tra theo tuyến thực tế, "
            f"giữ SOC dự kiến tại đích {plan.final_arrival_soc_percent:.1f}% so với mức dự phòng {reserve:.1f}%."
        )
    else:
        summary = (
            f"Không cần sạc giữa chặng: SOC dự kiến tại đích {plan.final_arrival_soc_percent:.1f}%, "
            f"cao hơn hoặc bằng mức dự phòng {reserve:.1f}%."
        )
    return ExplanationPayload(
        summary_text=summary,
        selected_station_reasons=selected_reasons,
        rejected_station_reasons=rejected_reasons,
        references=references,
    )


def validate_grounded_explanation(
    explanation: ExplanationPayload,
    plan: PlanProposal,
    candidates: list[CandidateStation],
) -> bool:
    fallback = deterministic_explanation(plan, candidates)
    allowed_refs = {
        (ref.entity_type, ref.entity_id, ref.metric_name, str(ref.metric_value))
        for ref in fallback.references
    }
    output_refs = {
        (ref.entity_type, ref.entity_id, ref.metric_name, str(ref.metric_value))
        for ref in explanation.references
    }
    if not output_refs or not output_refs.issubset(allowed_refs):
        return False
    allowed_selected = set(fallback.selected_station_reasons)
    allowed_rejected = set(fallback.rejected_station_reasons)
    if not set(explanation.selected_station_reasons).issubset(allowed_selected):
        return False
    if not set(explanation.rejected_station_reasons).issubset(allowed_rejected):
        return False

    allowed_numbers = [
        float(ref.metric_value)
        for ref in fallback.references
        if isinstance(ref.metric_value, (int, float))
    ]
    text = " ".join(
        [explanation.summary_text]
        + list(explanation.selected_station_reasons.values())
        + list(explanation.rejected_station_reasons.values())
    )
    for token in _NUMBER_RE.findall(text):
        value = float(token.replace(",", "."))
        if not any(isclose(value, allowed, abs_tol=0.051) for allowed in allowed_numbers):
            return False
    allowed_names = {station.name.casefold() for station in candidates}
    allowed_names.update(stop.name.casefold() for stop in plan.charging_stops)
    allowed_ids = allowed_selected | allowed_rejected
    for quoted in _QUOTED_RE.findall(text):
        normalized = quoted.strip().casefold()
        if normalized not in allowed_names and quoted.strip() not in allowed_ids:
            return False
    return True


def _fact_payload(plan: PlanProposal, candidates: list[CandidateStation]) -> dict:
    fallback = deterministic_explanation(plan, candidates)
    return {
        "plan_id": plan.plan_id,
        "route": {
            "distance_km": plan.route.distance_km,
            "duration_min": plan.route.duration_min,
            "detour_distance_km": plan.route.detour_distance_km,
        },
        "energy": {
            "reserve_soc_percent": plan.assumptions.reserve_soc_percent,
            "final_soc_percent": plan.final_arrival_soc_percent,
        },
        "selected_stations": [stop.model_dump(mode="json") for stop in plan.charging_stops],
        "candidate_stations": [station.__dict__ for station in candidates],
        "required_output": fallback.model_dump(mode="json"),
    }
