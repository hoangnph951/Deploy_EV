from src.packages.core.replanning.application.plan_diff import PlanDiffEngine, PlanMetrics


def test_plan_diff_uses_deterministic_metrics() -> None:
    old = PlanMetrics(
        distance_km=300.0, duration_min=300.0, final_soc_percent=18.0,
        min_soc_percent=16.0, station_ids=["ST-10"],
    )
    candidate = PlanMetrics(
        distance_km=315.0, duration_min=325.0, final_soc_percent=25.0,
        min_soc_percent=20.0, station_ids=["ST-20"],
    )

    diff = PlanDiffEngine().compare(old, candidate)

    assert diff.distance_delta_km == 15.0
    assert diff.duration_delta_min == 25.0
    assert diff.final_soc_delta_percent == 7.0
    assert diff.reserve_margin_delta_percent == 4.0
    assert diff.removed_station_ids == ["ST-10"]
    assert diff.added_station_ids == ["ST-20"]
