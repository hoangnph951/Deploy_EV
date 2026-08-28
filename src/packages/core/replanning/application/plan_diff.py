from __future__ import annotations

from pydantic import BaseModel, Field


class PlanMetrics(BaseModel):
    distance_km: float = Field(ge=0)
    duration_min: float = Field(ge=0)
    final_soc_percent: float = Field(ge=0, le=100)
    min_soc_percent: float = Field(ge=0, le=100)
    station_ids: list[str] = Field(default_factory=list)


class PlanDiff(BaseModel):
    distance_delta_km: float
    duration_delta_min: float
    final_soc_delta_percent: float
    reserve_margin_delta_percent: float
    removed_station_ids: list[str]
    added_station_ids: list[str]


class PlanDiffEngine:
    def compare(self, old: PlanMetrics, candidate: PlanMetrics) -> PlanDiff:
        old_ids = set(old.station_ids)
        candidate_ids = set(candidate.station_ids)
        return PlanDiff(
            distance_delta_km=round(candidate.distance_km - old.distance_km, 2),
            duration_delta_min=round(candidate.duration_min - old.duration_min, 1),
            final_soc_delta_percent=round(
                candidate.final_soc_percent - old.final_soc_percent, 1
            ),
            reserve_margin_delta_percent=round(
                candidate.min_soc_percent - old.min_soc_percent, 1
            ),
            removed_station_ids=[item for item in old.station_ids if item not in candidate_ids],
            added_station_ids=[item for item in candidate.station_ids if item not in old_ids],
        )
