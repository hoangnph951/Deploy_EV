from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from src.packages.contracts.trips import PlanProposal
from src.packages.core.monitoring.domain.risk import SOCRiskState

Provenance = Literal["REAL_GPS", "REAL_API", "SIMULATED", "CACHED_SNAPSHOT", "MANUAL"]
EventType = Literal[
    "ROUTE_DEVIATION",
    "SOC_UNDERPERFORMANCE",
    "STATION_UNAVAILABLE",
    "STALE_TELEMETRY",
]
SimulationStatus = Literal["IDLE", "RUNNING", "AWAITING_DECISION", "COMPLETED", "STOPPED"]


class MonitoringThresholds(BaseModel):
    max_off_route_distance_km: float = 2.0
    max_soc_drop_deviation_percent: float = 5.0
    max_telemetry_silent_seconds: float = 60.0


class SimulatorStartRequest(BaseModel):
    plan_id: str | None = None
    plan: PlanProposal | None = None
    seed: int = 42
    tick_interval_seconds: float = Field(default=1.0, gt=0, le=60)
    speed_multiplier: float | None = Field(default=None, gt=0, le=100)
    scenario: Literal[
        "RANDOM", "NORMAL", "ROUTE_DEVIATION", "SOC_UNDERPERFORMANCE",
        "STATION_UNAVAILABLE", "STALE_TELEMETRY",
    ] = "RANDOM"
    unhappy_probability: float = Field(default=0.5, ge=0, le=1)


class SimulationDecisionRequest(BaseModel):
    decision: Literal["REQUEST_REPLAN", "CONTINUE", "STOP"]


class TelemetrySnapshot(BaseModel):
    snapshot_id: str | None = None
    lat: float
    lon: float
    soc_percent: float
    expected_soc_percent: float
    speed_kph: float
    distance_km: float
    progress_percent: float
    distance_to_route_km: float = 0.0
    scenario_id: str = ""
    simulation_run_id: str = ""
    tick: int = 0
    source: Provenance = "SIMULATED"
    freshness: Literal["FRESH", "STALE"] = "FRESH"
    recorded_at: datetime
    age_seconds: float = 0.0

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_simulator_snapshot(cls, value):
        """Normalize the pre-F3-v2 simulator payload into the canonical shape."""
        if not isinstance(value, dict):
            return value
        data = dict(value)
        data.setdefault("lon", data.get("lng"))
        data.setdefault("soc_percent", data.get("actual_soc_percent"))
        data.setdefault("speed_kph", data.get("speed_kph", 0.0))
        data.setdefault("distance_km", data.get("distance_km", 0.0))
        data.setdefault("source", data.get("source_type", "SIMULATED"))
        data.setdefault("snapshot_id", data.get("event_id"))
        data.setdefault("age_seconds", data.get("age_seconds", 0.0))
        data.setdefault("distance_to_route_km", data.get("distance_to_route_km", 0.0))
        return data

    @property
    def actual_soc_percent(self) -> float:
        return self.soc_percent

    @property
    def lng(self) -> float:
        return self.lon

    @property
    def event_id(self) -> str:
        return self.snapshot_id or ""


class MonitoringEvent(BaseModel):
    event_id: str
    trip_id: str
    event_type: EventType
    occurred_at: datetime
    received_at: datetime
    telemetry_snapshot_id: str | None = None
    source_sequence: int | None = None
    related_plan_version: int = 0
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    threshold_ref: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    correlation_id: str
    causation_id: str | None = None
    station_ids: list[str] = Field(default_factory=list)
    station_id: str | None = None
    message: str = ""
    source: Provenance = "SIMULATED"
    payload: dict = Field(default_factory=dict)
    threshold_name: str = ""
    threshold_value: float | None = None
    actual_value: float | None = None
    telemetry_event_id: str = ""
    scenario_id: str = ""
    simulation_run_id: str = ""
    tick: int = 0
    reason_codes: list[str] = Field(default_factory=list)
    status: Literal["ACTIVE", "OBSOLETE", "RESOLVED"] = "ACTIVE"
    requires_agent_decision: bool = True

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_simulator_event(cls, value):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        created = data.pop("created_at", None) or datetime.now(UTC)
        data.setdefault("event_id", data.pop("id", None))
        data.setdefault("trip_id", "")
        data.setdefault("occurred_at", created)
        data.setdefault("received_at", created)
        data.setdefault("correlation_id", data.get("event_id"))
        data["severity"] = {"WARNING": "MEDIUM"}.get(data.get("severity"), data.get("severity"))
        station_id = data.get("station_id") or data.get("payload", {}).get("station_id")
        if station_id and not data.get("station_ids"):
            data["station_ids"] = [station_id]
        return data

    @property
    def id(self) -> str:
        return self.event_id

    @property
    def created_at(self) -> datetime:
        return self.received_at



class SimulationState(BaseModel):
    trip_id: str
    plan_id: str
    status: SimulationStatus
    selected_scenario: str
    telemetry: TelemetrySnapshot | None = None
    events: list[MonitoringEvent] = Field(default_factory=list)
    unavailable_station_ids: list[str] = Field(default_factory=list)
    replan_required: bool = False
    agent_invocation_count: int = 0
    tick_count: int = 0
    speed_multiplier: float = 1.0
    estimated_duration_seconds: int = 0
    soc_risk: SOCRiskState | None = None
