from src.packages.core.monitoring.application.periodic_risk import PeriodicRiskEvaluator
from src.packages.core.monitoring.domain.risk import SOCRiskState


def test_declining_soc_residual_warns_before_canonical_event() -> None:
    evaluator = PeriodicRiskEvaluator(warning_threshold=-3.0, event_threshold=-7.0)
    state = SOCRiskState.empty()
    for actual, expected in [(48, 50), (46, 50), (45, 50)]:
        state = evaluator.observe(actual_soc_percent=actual, expected_soc_percent=expected, prior=state)
    assert state.warning_level == "WARNING"
    assert state.residual_slope < 0


def test_single_noisy_sample_does_not_emit_event() -> None:
    state = PeriodicRiskEvaluator(event_threshold=-7.0, event_breach_count=2).observe(
        actual_soc_percent=40, expected_soc_percent=50, prior=SOCRiskState.empty()
    )
    assert state.warning_level != "EVENT"


def test_consecutive_threshold_breaches_emit_canonical_event() -> None:
    evaluator = PeriodicRiskEvaluator(event_threshold=-7.0, event_breach_count=2)
    first = evaluator.observe(
        actual_soc_percent=42, expected_soc_percent=50, prior=SOCRiskState.empty()
    )
    second = evaluator.observe(actual_soc_percent=41, expected_soc_percent=50, prior=first)
    assert second.warning_level == "EVENT"
