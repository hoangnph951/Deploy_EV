from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.packages.contracts.monitoring import MonitoringEvent, TelemetrySnapshot
from src.packages.contracts.replanning import AgentDecision
from src.packages.contracts.trips import PlanProposal

SimulationProfile = Literal[
    "NORMAL",
    "ROUTE_DEVIATION",
    "SOC_UNDERPERFORMANCE",
    "STATION_UNAVAILABLE",
    "STALE_TELEMETRY",
    "NO_FEASIBLE_ALTERNATIVE",
]


class SimulationChargingStation(BaseModel):
    station_id: str
    name: str
    lat: float
    lng: float
    address: str = ""
    arrival_soc_percent: float | None = None
    departure_soc_percent: float | None = None
    charge_duration_min: float | None = None
    max_power_kw: float | None = None
    connector_type: str = ""
    station_status: str = "UNKNOWN"


class SimulationCase(BaseModel):
    case_id: str
    base_case_id: str
    log_file: str
    run_id: str
    origin_name: str
    destination_name: str
    initial_soc_percent: float
    profile: SimulationProfile
    provider: str
    distance_km: float
    charging_stop_count: int
    readiness: Literal["READY", "NOT_APPLICABLE", "INVALID"]
    readiness_reason: str | None = None


class SimulationCatalogResponse(BaseModel):
    target_case_count: int = 90
    available_base_log_count: int
    generated_case_count: int
    ready_case_count: int
    cases: list[SimulationCase]


class SimulationStartRequest(BaseModel):
    case_id: str
    speed_multiplier: int = Field(default=10, ge=1, le=50)
    idempotency_key: str = Field(min_length=1, max_length=128)


class SimulationRunResponse(BaseModel):
    run_id: str
    owner_id: str
    case: SimulationCase
    status: Literal["RUNNING", "PAUSED", "AWAITING_ACTION", "COMPLETED", "FAILED"]
    current_tick: int
    total_ticks: int
    speed_multiplier: int
    started_at: datetime
    updated_at: datetime
    telemetry: TelemetrySnapshot | None = None
    route_polyline: list[tuple[float, float]] = Field(default_factory=list)
    original_route_polyline: list[tuple[float, float]] = Field(default_factory=list)
    actual_path: list[tuple[float, float]] = Field(default_factory=list)
    charging_stations: list[SimulationChargingStation] = Field(default_factory=list)
    requires_user_action: bool = False
    applied_action: str | None = None
    replanned_plan: PlanProposal | None = None
    monitoring_events: list[MonitoringEvent] = Field(default_factory=list)
    agent_decisions: list[AgentDecision] = Field(default_factory=list)
    error_code: str | None = None
