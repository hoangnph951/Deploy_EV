from __future__ import annotations

from src.packages.core.monitoring.domain.risk import SOCRiskState


class PeriodicRiskEvaluator:
    def __init__(
        self,
        *,
        warning_threshold: float = -3.0,
        event_threshold: float = -5.0,
        warning_negative_count: int = 2,
        event_breach_count: int = 3,
        critical_threshold: float = -15.0,
    ):
        self.warning_threshold = warning_threshold
        self.event_threshold = event_threshold
        self.warning_negative_count = warning_negative_count
        self.event_breach_count = event_breach_count
        self.critical_threshold = critical_threshold

    def observe(
        self,
        *,
        actual_soc_percent: float,
        expected_soc_percent: float,
        prior: SOCRiskState,
    ) -> SOCRiskState:
        residual = actual_soc_percent - expected_soc_percent
        slope = residual - prior.residual_percent
        negative_count = prior.consecutive_negative_count + 1 if slope < 0 else 0
        breach_count = (
            prior.consecutive_threshold_breach_count + 1
            if residual <= self.event_threshold
            else 0
        )
        if residual <= self.critical_threshold or breach_count >= self.event_breach_count:
            level = "EVENT"
        elif residual <= self.warning_threshold and negative_count >= self.warning_negative_count:
            level = "WARNING"
        elif residual < 0:
            level = "WATCH"
        else:
            level = "NONE"
        return SOCRiskState(
            expected_soc_percent=expected_soc_percent,
            actual_soc_percent=actual_soc_percent,
            residual_percent=residual,
            residual_slope=slope,
            consecutive_negative_count=negative_count,
            consecutive_threshold_breach_count=breach_count,
            warning_level=level,
        )
