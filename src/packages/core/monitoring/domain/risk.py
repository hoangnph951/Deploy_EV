from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class SOCRiskState(BaseModel):
    expected_soc_percent: float
    actual_soc_percent: float
    residual_percent: float
    residual_slope: float | None = None
    consecutive_negative_count: int = 0
    consecutive_threshold_breach_count: int = 0
    warning_level: Literal["NONE", "WATCH", "WARNING", "EVENT"] = "NONE"

    @classmethod
    def empty(cls) -> "SOCRiskState":
        return cls(expected_soc_percent=0, actual_soc_percent=0, residual_percent=0)
