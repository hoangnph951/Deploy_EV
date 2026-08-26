from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyConfig:
    id: str
    policy_version: str
    reserve_soc_percent: float
    stale_station_hours_threshold: float
    route_deviation_km_threshold: float
    active: bool = True

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("Policy id must not be empty.")
        if not self.policy_version.strip():
            raise ValueError("Policy version must not be empty.")
        if not 0 < self.reserve_soc_percent < 100:
            raise ValueError("reserve_soc_percent must be between 0 and 100.")
        if self.stale_station_hours_threshold <= 0:
            raise ValueError("stale_station_hours_threshold must be positive.")
        if self.route_deviation_km_threshold <= 0:
            raise ValueError("route_deviation_km_threshold must be positive.")


DEFAULT_POLICY = PolicyConfig(
    id="pilot-policy-v1",
    policy_version="pilot-policy-v1",
    reserve_soc_percent=15.0,
    stale_station_hours_threshold=24.0,
    route_deviation_km_threshold=2.0,
    active=True,
)
