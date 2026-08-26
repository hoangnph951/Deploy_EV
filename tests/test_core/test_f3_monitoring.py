from src.packages.contracts.monitoring import MonitoringThresholds
from src.packages.core.monitoring.application.service import MonitoringEvaluator, MonitoringSimulatorService


def test_normal_has_zero_unnecessary_agent_trigger():
    evaluator = MonitoringEvaluator()
    assert evaluator.classify(off_route_distance_km=1.99, soc_deficit_percent=4.9, silent_seconds=59) == "NORMAL"


def test_thresholds_are_strictly_greater_than_proposal_values():
    evaluator = MonitoringEvaluator(MonitoringThresholds())
    assert evaluator.classify(off_route_distance_km=2.0) == "NORMAL"
    assert evaluator.classify(off_route_distance_km=2.01) == "ROUTE_DEVIATION"
    assert evaluator.classify(soc_deficit_percent=5.0) == "NORMAL"
    assert evaluator.classify(soc_deficit_percent=5.1) == "SOC_UNDERPERFORMANCE"
    assert evaluator.classify(silent_seconds=60) == "NORMAL"
    assert evaluator.classify(silent_seconds=61) == "STALE_TELEMETRY"


def test_station_unavailable_is_explicit_simulator_event():
    assert MonitoringEvaluator().classify(station_unavailable=True) == "STATION_UNAVAILABLE"


def test_simulation_pacing_scales_with_trip_distance():
    short_multiplier, short_seconds = MonitoringSimulatorService._simulation_pacing(10, None)
    long_multiplier, long_seconds = MonitoringSimulatorService._simulation_pacing(1000, None)
    assert long_multiplier > short_multiplier
    assert short_seconds < long_seconds <= 300
    assert short_seconds >= 60
