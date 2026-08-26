from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.packages.contracts.trips import PlanProposal

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
    unhappy_probability: float = Field(default=0.35, ge=0, le=1)


class SimulationDecisionRequest(BaseModel):
    decision: Literal["REQUEST_REPLAN", "CONTINUE", "STOP"]


class TelemetrySnapshot(BaseModel):
    lat: float
    lon: float
    soc_percent: float
    expected_soc_percent: float
    speed_kph: float
    distance_km: float
    progress_percent: float
    source: Provenance = "SIMULATED"
    freshness: Literal["FRESH", "STALE"] = "FRESH"
    recorded_at: datetime


class MonitoringEvent(BaseModel):
    id: str
    trip_id: str
    event_type: EventType
    severity: Literal["WARNING", "CRITICAL"]
    message: str
    source: Provenance = "SIMULATED"
    payload: dict = Field(default_factory=dict)
    created_at: datetime


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
