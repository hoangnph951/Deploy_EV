from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class TripStatus(StrEnum):
    DRAFT = "DRAFT"
    PLANNING = "PLANNING"
    PLANNED = "PLANNED"
    PLANNING_FAILED = "PLANNING_FAILED"
    # Kept readable for records created by later feature slices. Feature 1
    # never transitions a trip into these states.
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class VehicleProfile:
    id: str
    version: str
    name: str
    battery_capacity_kwh: float
    usable_capacity_kwh: float
    max_charging_power_kw: float
    connector_type: str
    consumption_curve_json: str


@dataclass(frozen=True)
class AssumptionSnapshotData:
    policy_version: str
    reserve_soc_percent: float
    ambient_temperature_c: float
    vehicle_payload_kg: float
    vehicle_profile_version: str
    source: str
    created_at: datetime


@dataclass(frozen=True)
class ResolvedLocationData:
    address: str
    lat: float
    lng: float
    source_type: str


@dataclass(frozen=True)
class TripRecord:
    id: str
    owner_id: str
    status: str
    origin_address: str
    origin_lat: float
    origin_lng: float
    origin_source_type: str
    destination_address: str
    destination_lat: float
    destination_lng: float
    destination_source_type: str
    initial_soc_percent: float
    soc_source_type: str
    vehicle_profile_id: str
    preference: str
    assumptions_json: str
    created_at: datetime
    updated_at: datetime
    confirmed_plan_version: int | None = None


@dataclass(frozen=True)
class PlanVersionRecord:
    id: str
    trip_id: str
    version: int
    status: str
    assumptions_json: str
    proposal_json: str
    created_at: datetime
    updated_at: datetime
    planning_run_id: str | None = None
    rank: int = 1
    strategy: str = "BALANCED"
    is_primary: bool = True
    decision_reason: str | None = None


@dataclass(frozen=True)
class PlanningRunRecord:
    id: str
    trip_id: str
    status: str
    request_snapshot_json: str
    trace_id: str | None
    started_at: datetime | None
    finished_at: datetime | None
    result_code: str | None
    error_code: str | None
    error_detail_json: str | None

