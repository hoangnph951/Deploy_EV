from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

LocationSourceType = Literal["MANUAL", "REAL_API", "CACHED_SNAPSHOT", "SIMULATED"]
SocSourceType = Literal["MANUAL", "SIMULATED"]
PreferenceType = Literal["balanced"]
SafetyVerdictType = Literal["FEASIBLE", "RISKY", "INFEASIBLE"]
SafetyReasonCode = Literal[
    "SOC_BELOW_RESERVE_15",
    "INITIAL_SOC_BELOW_RESERVE",
    "NO_COMPATIBLE_CONNECTOR",
    "UNREACHABLE_NEXT_STATION",
    "STALE_STATION_DATA",
    "ROUTING_UNAVAILABLE",
    "TIGHT_ENERGY_MARGIN",
    "STATION_BUSY",
    "UNVERIFIED_STATION_DATA",
    "DETOUR_DISTANCE_EXCEEDED",
    "DETOUR_TIME_EXCEEDED",
    "ENVIRONMENT_DATA_FALLBACK",
]


class TripLocationInput(BaseModel):
    address: str | None = Field(default=None, description="Free-text address entered by the user")
    lat: float | None = Field(default=None, ge=-90, le=90, description="Latitude")
    lng: float | None = Field(default=None, ge=-180, le=180, description="Longitude")
    source_type: LocationSourceType = Field(default="MANUAL")

    @model_validator(mode="after")
    def validate_shape(self) -> TripLocationInput:
        has_address = bool(self.address and self.address.strip())
        has_any_coord = self.lat is not None or self.lng is not None

        if not has_address and not has_any_coord:
            raise ValueError("Provide either address or both lat/lng.")

        if (self.lat is None) != (self.lng is None):
            raise ValueError("Both lat and lng are required when using coordinates.")

        return self


class TripCreateRequest(BaseModel):
    origin: TripLocationInput
    destination: TripLocationInput
    initial_soc_percent: float = Field(..., description="Initial battery percentage")
    soc_source_type: SocSourceType = Field(default="MANUAL")
    vehicle_profile_id: str = Field(default="vinfast-vf6-plus-v1")
    preference: PreferenceType = Field(default="balanced")

    @model_validator(mode="after")
    def validate_business_rules(self) -> TripCreateRequest:
        if not 1 <= self.initial_soc_percent <= 100:
            raise ValueError("initial_soc_percent must be between 1 and 100.")
        if self.preference != "balanced":
            raise ValueError("Only preference='balanced' is supported in MVP.")
        return self


class AmbiguousLocationCandidate(BaseModel):
    label: str
    lat: float
    lng: float


class VehicleProfileSnapshot(BaseModel):
    id: str
    name: str
    version: str
    battery_capacity_kwh: float = Field(..., gt=0)
    usable_capacity_kwh: float = Field(..., gt=0)
    max_charging_power_kw: float = Field(..., gt=0)
    connector_type: str
    baseline_wh_per_km: float = Field(..., gt=0)
    reference_range_km: float | None = Field(default=None, gt=0)
    reference_range_standard: str | None = None
    brochure_range_km: float | None = Field(default=None, gt=0)
    brochure_range_standard: str | None = None
    motor_power_kw: float | None = Field(default=None, gt=0)
    max_torque_nm: float | None = Field(default=None, gt=0)
    drive_type: str | None = None
    seats: int | None = Field(default=None, gt=0)
    curb_weight_kg: float | None = Field(default=None, gt=0)
    dimensions_mm: str | None = None
    wheelbase_mm: float | None = Field(default=None, gt=0)
    ground_clearance_mm: float | None = Field(default=None, gt=0)
    wheel_size_inch: float | None = Field(default=None, gt=0)
    fast_charge_10_70_min: float | None = Field(default=None, gt=0)
    official_source_url: str | None = None


class AssumptionSnapshot(BaseModel):
    policy_version: str
    reserve_soc_percent: float = Field(..., gt=0, lt=100)
    ambient_temperature_c: float
    vehicle_payload_kg: float = Field(..., ge=0)
    vehicle_profile_version: str
    vehicle_profile: VehicleProfileSnapshot | None = None
    source: Literal["POLICY_CONFIG"] = "POLICY_CONFIG"
    created_at: datetime


class TripCreatedResponse(BaseModel):
    trip_id: str
    status: str
    assumptions: AssumptionSnapshot
    created_at: datetime


class TripLocationResponse(BaseModel):
    address: str
    lat: float
    lng: float
    source_type: LocationSourceType


class InitialSocResponse(BaseModel):
    value_percent: float
    source_type: SocSourceType


class TripTelemetrySnapshot(BaseModel):
    location: TripLocationResponse | None = None
    soc: InitialSocResponse | None = None
    updated_at: datetime | None = None


class TripDetailResponse(BaseModel):
    trip_id: str
    status: str
    owner_id: str
    origin: TripLocationResponse
    destination: TripLocationResponse
    initial_soc: InitialSocResponse
    assumptions: AssumptionSnapshot
    confirmed_plan_version: int | None = None
    latest_telemetry: TripTelemetrySnapshot | None = None
    active_warnings: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class RouteSegment(BaseModel):
    from_name: str
    to_name: str
    distance_km: float
    duration_min: float
    start_lat: float
    start_lng: float
    end_lat: float
    end_lng: float


class RouteGeometry(BaseModel):
    polyline: list[list[float]] = Field(
        default_factory=list,
        description="Array of [lat, lng] points representing the route polyline",
    )
    distance_km: float = Field(..., ge=0)
    duration_min: float = Field(..., ge=0)
    segments: list[RouteSegment] = Field(default_factory=list)
    provider: str = "GOONG_DIRECTIONS"
    source_url: str = ""
    retrieved_at: datetime | None = None
    direct_distance_km: float | None = Field(default=None, ge=0)
    detour_distance_km: float = Field(default=0.0, ge=0)
    detour_duration_min: float = Field(default=0.0, ge=0)
    includes_backtracking: bool = False


class DataProvenance(BaseModel):
    source: Literal[
        # Legacy values remain readable for plan snapshots created before the
        # Goong migration; runtime providers no longer emit them.
        "OSRM",
        "GOOGLE_ROUTES",
        "GOONG_DIRECTIONS",
        "VINFAST_OFFICIAL",
        "OPENAI_WEB_SEARCH",
        "OPEN_METEO_WEATHER",
        "OPEN_METEO_ELEVATION",
        "POLICY_FALLBACK",
        "VEHICLE_PROFILE",
        "TEST_FIXTURE",
    ]
    source_url: str
    retrieved_at: datetime
    source_updated_at: datetime | None = None
    version: str | None = None


class EnvironmentSnapshot(BaseModel):
    temperature_c: float
    precipitation_mm: float = Field(default=0.0, ge=0)
    wind_speed_kmh: float = Field(default=0.0, ge=0)
    elevation_gain_m: float = Field(default=0.0, ge=0)
    elevation_loss_m: float = Field(default=0.0, ge=0)
    weather_provenance: DataProvenance
    elevation_provenance: DataProvenance
    status: Literal["LIVE", "CACHED", "WEB_SEARCH", "POLICY_FALLBACK"] = "LIVE"
    is_degraded: bool = False
    consumption_margin_percent: float = Field(default=0.0, ge=0, le=100)
    warning: str | None = None


class SocPoint(BaseModel):
    distance_km: float = Field(..., ge=0)
    soc_percent: float
    kind: Literal["ORIGIN", "ARRIVAL", "DEPARTURE", "DESTINATION"]
    label: str


class ChargingStopProposal(BaseModel):
    station_id: str
    name: str
    lat: float
    lon: float
    address: str = ""
    arrival_soc_percent: float = Field(..., description="Estimated battery percentage upon arrival")
    departure_soc_percent: float = Field(..., description="Target battery percentage upon departure")
    charge_duration_min: float = Field(..., ge=0, description="Estimated charging duration in minutes")
    energy_added_kwh: float = Field(..., ge=0, description="Energy added in kWh")
    max_power_kw: float = Field(..., gt=0, description="Verified station charging power in kW")
    connector_type: str
    connector_standard: str = ""
    port_count: int = Field(default=1, ge=1)
    station_status: str = "ACTIVE"
    opening_24_7: bool | None = None
    access_type: str = "Public"
    parking_fee: bool | None = None
    station_updated_at: datetime | None = None
    detour_distance_km: float = Field(default=0.0)
    detour_duration_min: float = Field(default=0.0)
    freshness: Literal["FRESH", "STALE"] = "FRESH"
    distance_from_origin_km: float = Field(default=0.0, ge=0)
    provenance: DataProvenance | None = None


class RiskAssessment(BaseModel):
    verdict: SafetyVerdictType = "FEASIBLE"
    level: Literal["LOW_RISK", "MEDIUM_RISK", "HIGH_RISK", "INFEASIBLE"] = "LOW_RISK"
    is_feasible: bool = True
    reasons: list[str] = Field(default_factory=list)
    reason_codes: list[SafetyReasonCode] = Field(default_factory=list)
    risk_score: float = Field(default=0.0, ge=0, le=100)


class ExplanationReference(BaseModel):
    entity_type: Literal["STATION", "ROUTE", "ENERGY"]
    entity_id: str
    metric_name: str
    metric_value: float | str


ExplanationReferences = ExplanationReference


class ExplanationPayload(BaseModel):
    summary_text: str
    selected_station_reasons: dict[str, str] = Field(default_factory=dict)
    rejected_station_reasons: dict[str, str] = Field(default_factory=dict)
    references: list[ExplanationReference] = Field(default_factory=list)


class PlanProposal(BaseModel):
    plan_id: str
    trip_id: str
    version: int = 1
    status: Literal[
        "PENDING", "CONDITIONAL", "CONFIRMED", "REJECTED", "SUPERSEDED",
        "STALE_BY_NEW_CONTEXT", "INVALIDATED_BY_SAFETY",
    ] = "PENDING"
    route: RouteGeometry
    charging_stops: list[ChargingStopProposal] = Field(default_factory=list)
    risk_assessment: RiskAssessment
    assumptions: AssumptionSnapshot
    soc_points: list[SocPoint] = Field(default_factory=list)
    final_arrival_soc_percent: float = 0.0
    effective_consumption_wh_per_km: float = Field(default=0.0, ge=0)
    environment: EnvironmentSnapshot | None = None
    provenance: list[DataProvenance] = Field(default_factory=list)
    summary: str = ""
    alternative_rank: int = Field(default=1, ge=1, le=3)
    strategy: Literal["BALANCED", "FASTEST", "SAFEST"] = "BALANCED"
    selection_reason: str = ""
    explanation_source: Literal["DETERMINISTIC", "OPENAI"] = "DETERMINISTIC"
    explanation: ExplanationPayload | None = None
    trigger_reason: str | None = None
    decision_reason: str | None = None
    created_at: datetime


class PlanCreatedResponse(BaseModel):
    outcome: Literal["PLAN_CREATED"] = "PLAN_CREATED"
    trip_id: str
    plan: PlanProposal
    alternatives: list[PlanProposal] = Field(default_factory=list, max_length=3)
    created_at: datetime


class NoFeasiblePlan(BaseModel):
    outcome: Literal["PROVEN_INFEASIBLE"] = "PROVEN_INFEASIBLE"
    trip_id: str
    risk_assessment: RiskAssessment
    assumptions: AssumptionSnapshot
    charging_stops: list[ChargingStopProposal] = Field(default_factory=list, max_length=0)
    summary: str
    minimum_initial_soc_percent: float | None = Field(default=None, ge=0, le=100)
    direct_route_distance_km: float | None = Field(default=None, ge=0)
    estimated_reachable_distance_km: float | None = Field(default=None, ge=0)
    estimated_energy_required_kwh: float | None = Field(default=None, ge=0)
    available_energy_before_reserve_kwh: float | None = Field(default=None, ge=0)
    energy_shortfall_kwh: float | None = Field(default=None, ge=0)
    estimated_minimum_charging_stops: int | None = Field(default=None, ge=0)
    vehicle_profile_name: str | None = None
    usable_battery_kwh: float | None = Field(default=None, ge=0)
    nearest_candidate_station_name: str | None = None
    nearest_candidate_station_distance_km: float | None = Field(default=None, ge=0)
    evaluated_station_count: int = Field(default=0, ge=0)
    suggestions: list[str] = Field(default_factory=list)
    search_scope: str = "ON_ROUTE_AND_BACKTRACK"
    created_at: datetime


class RecoveryOption(BaseModel):
    code: str
    title: str
    description: str
    action: Literal["RETRY", "CHANGE_ENDPOINT", "CHARGE_BEFORE_DEPARTURE", "CONFIRM_CONDITIONAL"] = "RETRY"
    verified: bool = False
    source_url: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)


class ConditionalPlanResponse(BaseModel):
    outcome: Literal["CONDITIONAL"] = "CONDITIONAL"
    trip_id: str
    plan: PlanProposal
    alternatives: list[PlanProposal] = Field(default_factory=list, max_length=3)
    recovery_options: list[RecoveryOption] = Field(default_factory=list)
    summary: str
    created_at: datetime


class ActionRequiredResponse(BaseModel):
    outcome: Literal["ACTION_REQUIRED"] = "ACTION_REQUIRED"
    trip_id: str
    summary: str
    failure_category: Literal["ROUTING_ENDPOINT", "STATION_DATA", "FEASIBILITY"]
    provider: str = ""
    provider_status: str | None = None
    http_status: int | None = Field(default=None, ge=400, le=599)
    retry_after_seconds: float | None = Field(default=None, ge=0)
    recovery_options: list[RecoveryOption] = Field(default_factory=list)
    created_at: datetime


PlanningRecoveryResponse = ConditionalPlanResponse | ActionRequiredResponse
PlanGenerationResponse = PlanCreatedResponse | NoFeasiblePlan | PlanningRecoveryResponse


class PlanVersionSummary(BaseModel):
    id: str
    version: int
    version_number: int | None = None
    status: str
    created_at: datetime
    updated_at: datetime
    total_distance_km: float = 0.0
    total_duration_min: float = 0.0
    stop_count: int = 0
    risk_level: str = ""
    trigger_reason: str = ""
    decision_reason: str | None = None


class PlanListResponse(BaseModel):
    trip_id: str
    plans: list[PlanProposal]
    history: list[PlanVersionSummary] = Field(default_factory=list)


class PlanRejectRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)


class PlanDecisionResponse(BaseModel):
    plan: PlanProposal
    trip: TripDetailResponse
    action: Literal["CONFIRMED", "REJECTED"]


class PlanDetailResponse(BaseModel):
    plan: PlanProposal


class TripHistoryItem(BaseModel):
    trip_id: str
    status: str
    origin: TripLocationResponse
    destination: TripLocationResponse
    initial_soc: InitialSocResponse
    selected_plan: PlanProposal
    selected_at: datetime
    created_at: datetime


class TripHistoryResponse(BaseModel):
    trips: list[TripHistoryItem]


class ReplanRequest(BaseModel):
    current_lat: float = Field(..., ge=-90, le=90)
    current_lon: float = Field(..., ge=-180, le=180)
    current_soc_percent: float = Field(..., ge=0, le=100)
    excluded_station_ids: list[str] = Field(default_factory=list)
