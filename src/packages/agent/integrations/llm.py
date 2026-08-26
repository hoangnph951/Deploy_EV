from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from src.packages.contracts.trips import PlanProposal


class SafePlanRanking(BaseModel):
    selected_plan_id: str
    explanations: dict[str, str] = Field(default_factory=dict)


class OpenAISafePlanRanker:
    """Optional adapter; it cannot create, edit, or validate plan facts."""

    def __init__(self, *, api_key: str, model: str, timeout_seconds: float):
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds

    def rank(self, plans: list[PlanProposal]) -> list[PlanProposal]:
        if not self._api_key or len(plans) < 2:
            return plans

        safe_plans = [plan for plan in plans if plan.risk_assessment.is_feasible]
        if len(safe_plans) != len(plans):
            return plans
        facts = [
        {
            "plan_id": plan.plan_id,
            "strategy": plan.strategy,
            "distance_km": plan.route.distance_km,
            "duration_min": plan.route.duration_min,
            "charge_time_min": sum(stop.charge_duration_min for stop in plan.charging_stops),
            "detour_distance_km": plan.route.detour_distance_km,
            "includes_backtracking": plan.route.includes_backtracking,
            "final_soc_percent": plan.final_arrival_soc_percent,
            "minimum_soc_percent": min(point.soc_percent for point in plan.soc_points),
            "risk_level": plan.risk_assessment.level,
        }
        for plan in safe_plans
        ]
        prompt = (
        "Bạn chỉ được xếp hạng các phương án EV đã được safety engine xác minh dưới đây. "
        "Không thêm tuyến, trạm, SOC hoặc dữ kiện mới. Chọn một plan_id cân bằng nhất và "
        "giải thích ngắn cho từng plan_id dựa đúng vào JSON này:\n"
        f"{facts}"
        )
        try:
            llm = ChatOpenAI(
                model=self._model,
                api_key=self._api_key,
                temperature=0.0,
                timeout=self._timeout_seconds,
                max_retries=1,
            ).with_structured_output(SafePlanRanking)
            ranking = llm.invoke(prompt)
        except Exception:
            return plans

        valid_ids = {plan.plan_id for plan in safe_plans}
        if ranking.selected_plan_id not in valid_ids:
            return plans
        ordered = sorted(
        safe_plans,
        key=lambda plan: (plan.plan_id != ranking.selected_plan_id, plan.alternative_rank),
        )
        for rank, plan in enumerate(ordered, start=1):
            explanation = ranking.explanations.get(plan.plan_id, "").strip()
            plan.alternative_rank = rank
            if explanation:
                plan.selection_reason = explanation
                plan.explanation_source = "OPENAI"
        return ordered
