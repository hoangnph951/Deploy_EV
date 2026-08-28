export type LocationSourceType = "MANUAL" | "REAL_API" | "CACHED_SNAPSHOT" | "SIMULATED";
export type SocSourceType = "MANUAL" | "SIMULATED";

export type TripLocationInput = {
  address: string | null;
  lat: number | null;
  lng: number | null;
  source_type: LocationSourceType;
};

export type TripCreatePayload = {
  origin: TripLocationInput;
  destination: TripLocationInput;
  initial_soc_percent: number;
  soc_source_type: SocSourceType;
  vehicle_profile_id: string;
  preference: "balanced";
};

export type PlaceSelection = {
  address: string;
  lat: number;
  lng: number;
  placeId: string | null;
};

export type PlacePrediction = {
  place_id: string;
  description: string;
  main_text: string;
  secondary_text: string;
};

export type PlaceAutocompleteResponse = {
  predictions: PlacePrediction[];
};

export type PlaceDetailResponse = {
  place_id: string;
  name: string;
  formatted_address: string;
  lat: number;
  lng: number;
  provider: "GOONG_PLACES";
};

export type VehicleProfileSnapshot = {
  id: string;
  name: string;
  version: string;
  battery_capacity_kwh: number;
  usable_capacity_kwh: number;
  max_charging_power_kw: number;
  connector_type: string;
  baseline_wh_per_km: number;
  reference_range_km: number | null;
  reference_range_standard: string | null;
  brochure_range_km: number | null;
  brochure_range_standard: string | null;
  motor_power_kw: number | null;
  max_torque_nm: number | null;
  drive_type: string | null;
  seats: number | null;
  curb_weight_kg: number | null;
  dimensions_mm: string | null;
  wheelbase_mm: number | null;
  ground_clearance_mm: number | null;
  wheel_size_inch: number | null;
  fast_charge_10_70_min: number | null;
  official_source_url: string | null;
};

export type AuthUser = {
  id: string;
  full_name: string;
  email: string;
  phone: string | null;
  created_at: string;
};

export type AuthTokenResponse = {
  access_token: string;
  token_type: "bearer";
  expires_at: string;
  user: AuthUser;
  needs_vehicle_setup: boolean;
};

export type RegisterPayload = {
  full_name: string;
  email: string;
  phone: string | null;
  password: string;
  password_confirmation: string;
  accepted_terms: boolean;
};

export type LoginPayload = {
  email: string;
  password: string;
  remember_me: boolean;
};

export type UserVehicle = {
  id: string;
  nickname: string | null;
  license_plate: string | null;
  is_default: boolean;
  vehicle_profile: VehicleProfileSnapshot;
  created_at: string;
};

export type UserVehicleCreatePayload = {
  vehicle_profile_id: string;
  nickname: string | null;
  license_plate: string | null;
  make_default: boolean;
};

export type AssumptionSnapshot = {
  policy_version: string;
  reserve_soc_percent: number;
  ambient_temperature_c: number;
  vehicle_payload_kg: number;
  vehicle_profile_version: string;
  vehicle_profile: VehicleProfileSnapshot | null;
  stale_station_hours_threshold: number;
  route_deviation_km_threshold: number;
  planner_algorithm_version: string;
  energy_model_version: string;
  station_dataset_generation: string | null;
  routing_provider: string;
  road_version: string;
  source: "POLICY_CONFIG";
  created_at: string;
};

export type TripCreatedResponse = {
  trip_id: string;
  status: "DRAFT";
  assumptions: AssumptionSnapshot;
  created_at: string;
};

export type AmbiguousCandidate = {
  label: string;
  lat: number;
  lng: number;
};

export type RouteSegment = {
  from_name: string;
  to_name: string;
  distance_km: number;
  duration_min: number;
  start_lat: number;
  start_lng: number;
  end_lat: number;
  end_lng: number;
};

export type RouteGeometry = {
  polyline: number[][]; // [lat, lng]
  distance_km: number;
  duration_min: number;
  segments: RouteSegment[];
  provider: string;
  source_url: string;
  retrieved_at: string | null;
  direct_distance_km: number | null;
  detour_distance_km: number;
  detour_duration_min: number;
  includes_backtracking: boolean;
};

export type DataProvenance = {
  kind: "ROUTE" | "STATION_DATASET" | "STATION_DETAIL" | "WEATHER" | "ELEVATION" | "VEHICLE_PROFILE" | "POLICY_CONFIG" | "PLANNER_ALGORITHM" | "ENERGY_MODEL" | null;
  source: string;
  source_url: string;
  retrieved_at: string;
  source_updated_at: string | null;
  version: string | null;
  generation: string | null;
  served_at: string | null;
};

export type EnvironmentSnapshot = {
  temperature_c: number;
  precipitation_mm: number;
  wind_speed_kmh: number;
  elevation_gain_m: number;
  elevation_loss_m: number;
  weather_provenance: DataProvenance;
  elevation_provenance: DataProvenance;
  status: "LIVE" | "CACHED" | "WEB_SEARCH" | "POLICY_FALLBACK";
  is_degraded: boolean;
  consumption_margin_percent: number;
  warning: string | null;
};

export type SocPoint = {
  distance_km: number;
  soc_percent: number;
  kind: "ORIGIN" | "ARRIVAL" | "DEPARTURE" | "DESTINATION";
  label: string;
};

export type ChargingStopProposal = {
  station_id: string;
  name: string;
  lat: number;
  lon: number;
  address: string;
  arrival_soc_percent: number;
  departure_soc_percent: number;
  charge_duration_min: number;
  energy_added_kwh: number;
  max_power_kw: number;
  connector_type: string;
  connector_standard: string;
  port_count: number;
  station_status: string;
  opening_24_7: boolean | null;
  access_type: string;
  parking_fee: boolean | null;
  station_updated_at: string | null;
  detour_distance_km: number;
  detour_duration_min: number;
  freshness: "FRESH" | "STALE";
  distance_from_origin_km: number;
  provenance: DataProvenance | null;
};

export type RiskAssessment = {
  verdict: "FEASIBLE" | "RISKY" | "INFEASIBLE";
  level: "LOW_RISK" | "MEDIUM_RISK" | "HIGH_RISK" | "INFEASIBLE";
  is_feasible: boolean;
  reasons: string[];
  reason_codes: string[];
  risk_score: number;
};

export type ExplanationReference = {
  entity_type: "STATION" | "ROUTE" | "ENERGY";
  entity_id: string;
  metric_name: string;
  metric_value: number | string;
};

export type ExplanationPayload = {
  summary_text: string;
  selected_station_reasons: Record<string, string>;
  rejected_station_reasons: Record<string, string>;
  references: ExplanationReference[];
};

export type PlanProposal = {
  plan_id: string;
  trip_id: string;
  version: number;
  status: "PENDING" | "CONDITIONAL" | "CONFIRMED" | "REJECTED" | "SUPERSEDED";
  route: RouteGeometry;
  charging_stops: ChargingStopProposal[];
  risk_assessment: RiskAssessment;
  assumptions: AssumptionSnapshot;
  soc_points: SocPoint[];
  final_arrival_soc_percent: number;
  effective_consumption_wh_per_km: number;
  environment: EnvironmentSnapshot | null;
  provenance: DataProvenance[];
  summary: string;
  alternative_rank: number;
  strategy: "BALANCED" | "FASTEST" | "SAFEST";
  selection_reason: string;
  explanation_source: "DETERMINISTIC" | "OPENAI";
  explanation: ExplanationPayload | null;
  trigger_reason: string;
  decision_reason: string | null;
  created_at: string;
};

export type PlanCreatedResponse = {
  outcome: "PLAN_CREATED";
  trip_id: string;
  plan: PlanProposal;
  alternatives: PlanProposal[];
  created_at: string;
};

export type NoFeasiblePlan = {
  outcome: "PROVEN_INFEASIBLE";
  trip_id: string;
  risk_assessment: RiskAssessment;
  assumptions: AssumptionSnapshot;
  charging_stops: [];
  summary: string;
  minimum_initial_soc_percent: number | null;
  direct_route_distance_km: number | null;
  estimated_reachable_distance_km: number | null;
  estimated_energy_required_kwh: number | null;
  available_energy_before_reserve_kwh: number | null;
  energy_shortfall_kwh: number | null;
  estimated_minimum_charging_stops: number | null;
  vehicle_profile_name: string | null;
  usable_battery_kwh: number | null;
  nearest_candidate_station_name: string | null;
  nearest_candidate_station_distance_km: number | null;
  evaluated_station_count: number;
  suggestions: string[];
  search_scope: string;
  created_at: string;
};

export type RecoveryOption = {
  code: string;
  title: string;
  description: string;
  action: "RETRY" | "CHANGE_ENDPOINT" | "CHARGE_BEFORE_DEPARTURE" | "CONFIRM_CONDITIONAL";
  verified: boolean;
  source_url: string | null;
  lat: number | null;
  lng: number | null;
};

export type ConditionalPlanResponse = {
  outcome: "CONDITIONAL";
  trip_id: string;
  plan: PlanProposal;
  alternatives: PlanProposal[];
  recovery_options: RecoveryOption[];
  summary: string;
  created_at: string;
};

export type ActionRequiredResponse = {
  outcome: "ACTION_REQUIRED";
  trip_id: string;
  summary: string;
  failure_category: "ROUTING_ENDPOINT" | "STATION_DATA" | "FEASIBILITY";
  provider: string;
  provider_status: string | null;
  http_status: number | null;
  recovery_options: RecoveryOption[];
  created_at: string;
};

export type SearchExhaustedResponse = {
  outcome: "SEARCH_EXHAUSTED";
  trip_id: string;
  summary: string;
  search_scope: string;
  evaluated_station_count: number;
  reason_codes: string[];
  recovery_options: RecoveryOption[];
  created_at: string;
};

export type PlanningRecoveryResponse =
  | ConditionalPlanResponse
  | ActionRequiredResponse
  | SearchExhaustedResponse;
export type PlanGenerationResponse = PlanCreatedResponse | NoFeasiblePlan | PlanningRecoveryResponse;

export type PlanListResponse = {
  trip_id: string;
  plans: PlanProposal[];
  history: PlanVersionSummary[];
};

export type PlanVersionSummary = {
  id: string;
  version: number;
  version_number: number | null;
  status: PlanProposal["status"];
  created_at: string;
  updated_at: string;
  total_distance_km: number;
  total_duration_min: number;
  stop_count: number;
  risk_level: string;
  trigger_reason: string;
  decision_reason: string | null;
};

export type TripDetailResponse = {
  trip_id: string;
  status: string;
  owner_id: string;
  confirmed_plan_version: number | null;
};

export type PlanDecisionResponse = {
  plan: PlanProposal;
  trip: TripDetailResponse;
  action: "CONFIRMED" | "REJECTED";
};

export type TripHistoryItem = {
  trip_id: string;
  status: string;
  origin: { address: string; lat: number; lng: number; source_type: string };
  destination: { address: string; lat: number; lng: number; source_type: string };
  initial_soc: { value_percent: number; source_type: string };
  selected_plan: PlanProposal;
  selected_at: string;
  created_at: string;
};

export type TripHistoryResponse = { trips: TripHistoryItem[] };

export type ReplanningPlanDecisionResponse = {
  trip_id: string;
  plan_version: number;
  context_version: number;
  status: "CONFIRMED" | "REJECTED";
};
export type MonitoringEventType = "ROUTE_DEVIATION" | "SOC_UNDERPERFORMANCE" | "STATION_UNAVAILABLE" | "STALE_TELEMETRY";
export type SimulationScenarioSelection = "RANDOM" | "NORMAL" | MonitoringEventType;
export type SimulationState = {
  trip_id: string;
  plan_id: string;
  status: "IDLE" | "RUNNING" | "AWAITING_DECISION" | "COMPLETED" | "STOPPED";
  selected_scenario: "NORMAL" | MonitoringEventType;
  telemetry: null | {
    snapshot_id?: string | null;
    lat: number; lon: number; soc_percent: number; expected_soc_percent: number;
    speed_kph: number; distance_km: number; progress_percent: number;
    source: "SIMULATED"; freshness: "FRESH" | "STALE"; recorded_at: string;
  };
  events: Array<{
    event_id: string; event_type: MonitoringEventType; severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
    message: string; source: "SIMULATED"; payload: Record<string, unknown>;
    occurred_at: string; received_at: string; telemetry_snapshot_id: string | null;
    related_plan_version: number; evidence_refs: string[]; correlation_id: string;
    station_ids: string[];
    status: "ACTIVE" | "OBSOLETE" | "RESOLVED";
  }>;
  unavailable_station_ids: string[];
  replan_required: boolean;
  agent_invocation_count: number;
  tick_count: number;
  speed_multiplier: number;
  estimated_duration_seconds: number;
  soc_risk: null | {
    expected_soc_percent: number; actual_soc_percent: number; residual_percent: number;
    residual_slope: number | null; consecutive_negative_count: number;
    consecutive_threshold_breach_count: number; warning_level: "NONE" | "WATCH" | "WARNING" | "EVENT";
  };
};

export type ReplanningOutcome = {
  agent_run_id: string;
  status: "SUCCEEDED" | "INFEASIBLE" | "INSUFFICIENT_EVIDENCE" | "SEARCH_EXHAUSTED" | "FAILED";
  epoch: { epoch_id: string; event_ids: string[]; context_version: number; base_plan_version: number; status: string };
  context: {
    context_version: number; current_confirmed_plan_version: number; pending_plan_version: number | null;
    telemetry_snapshot_id: string; active_event_ids: string[];
    unresolved_constraints: {
      route_deviation_active: boolean; soc_underperformance_active: boolean; telemetry_blocked: boolean;
      excluded_station_ids: string[]; required_evidence: string[]; unresolved_reason_codes: string[];
    };
  };
  assessment: {
    primary_objective: string; urgency: string; strategy: string; known_facts: string[];
    constraints: string[]; missing_evidence: string[]; reason_codes: string[];
    evidence_refs: string[]; confidence: number;
    public_summary: string;
  };
  action: {
    action: string; reason_codes: string[]; evidence_refs: string[]; user_message: string;
    limitations: string[]; requires_owner_confirmation: boolean;
    public_summary: string;
  };
  tool_runs: Array<{
    sequence: number; tool: string; status: string; provider: string; freshness: string;
    provenance_refs: string[]; reason_codes: string[];
  }>;
  decision_trace: Array<{
    sequence: number; stage: string; summary_code: string; status: string;
    tool: string | null; evidence_refs: string[]; missing_evidence: string[];
    reason_codes: string[];
    public_summary: string;
  }>;
  candidate: null | {
    feasibility_verdict: string;
    plan_version?: number;
    strategy?: "MINIMAL_SUBSTITUTION" | "FULL_REPLAN";
    outcome?: PlanGenerationResponse;
  };
  plan_diff_id: string | null;
  plan_diff: null | {
    distance_delta_km: number; duration_delta_min: number; final_soc_delta_percent: number;
    reserve_margin_delta_percent: number; removed_station_ids: string[]; added_station_ids: string[];
  };
  reflection: {
    evidence_sufficient: boolean; hypothesis_status: string; missing_evidence: string[];
    next_step: string; next_tool: string | null; reason_codes: string[]; evidence_refs: string[];
    public_summary: string;
  };
  created_at: string;
};

export type ApiErrorEnvelope = {
  error: {
    code: string;
    message: string;
    details?: {
      field?: "origin" | "destination";
      candidates?: AmbiguousCandidate[];
      errors?: Array<{ loc: Array<string | number>; msg: string }>;
    };
    trace_id: string;
  };
};

export type SimulationProfile =
  | "NORMAL"
  | "ROUTE_DEVIATION"
  | "SOC_UNDERPERFORMANCE"
  | "STATION_UNAVAILABLE"
  | "STALE_TELEMETRY"
  | "NO_FEASIBLE_ALTERNATIVE";

export type SimulationCase = {
  case_id: string;
  base_case_id: string;
  log_file: string;
  run_id: string;
  origin_name: string;
  destination_name: string;
  initial_soc_percent: number;
  profile: SimulationProfile;
  provider: string;
  distance_km: number;
  charging_stop_count: number;
  readiness: "READY" | "NOT_APPLICABLE" | "INVALID";
  readiness_reason: string | null;
};

export type SimulationCatalog = {
  target_case_count: number;
  available_base_log_count: number;
  generated_case_count: number;
  ready_case_count: number;
  cases: SimulationCase[];
};

export type MonitoringEvent = {
  event_id: string;
  event_type: "ROUTE_DEVIATION" | "SOC_UNDERPERFORMANCE" | "STATION_UNAVAILABLE" | "STALE_TELEMETRY";
  severity: "WARNING" | "CRITICAL";
  threshold_name: string;
  threshold_value: number | null;
  actual_value: number | null;
  tick: number;
  station_id: string | null;
  reason_codes: string[];
};

export type AgentDecision = {
  agent_run_id: string;
  intent: "ROUTE_RECOVERY" | "ENERGY_RESCUE" | "STATION_SUBSTITUTION" | "TELEMETRY_RECOVERY";
  intent_confidence: number;
  classification_source: "AI_AGENT" | "DETERMINISTIC_FALLBACK";
  strategy: string;
  selected_tools: string[];
  action: string;
  action_guard: "PASSED" | "FALLBACK";
  requires_owner_confirmation: boolean;
  reason_codes: string[];
  evidence_refs: string[];
  explanation: string;
  limitations: string[];
  plan_diff: {
    distance_delta_km: number;
    duration_delta_min: number;
    final_soc_delta_percent: number;
    removed_station_ids: string[];
    added_station_ids: string[];
    old_safety: string;
    candidate_safety: string;
    summary: string;
  } | null;
  candidate_plan: {
    candidate_id: string;
    status: "PENDING";
    distance_km: number;
    duration_min: number;
    final_soc_percent: number;
    station_ids: string[];
    safety_verdict: "FEASIBLE" | "INFEASIBLE";
    simulation_only: boolean;
  } | null;
};

export type SimulationRun = {
  run_id: string;
  owner_id: string;
  case: SimulationCase;
  status: "RUNNING" | "PAUSED" | "AWAITING_ACTION" | "COMPLETED" | "FAILED";
  current_tick: number;
  total_ticks: number;
  speed_multiplier: number;
  started_at: string;
  updated_at: string;
  telemetry: {
    lat: number;
    lng: number;
    actual_soc_percent: number;
    expected_soc_percent: number;
    progress_percent: number;
    distance_to_route_km: number;
    age_seconds: number;
    tick: number;
  } | null;
  route_polyline: Array<[number, number]>;
  original_route_polyline: Array<[number, number]>;
  actual_path: Array<[number, number]>;
  charging_stations: Array<{
    station_id: string;
    name: string;
    lat: number;
    lng: number;
    address: string;
    arrival_soc_percent: number | null;
    departure_soc_percent: number | null;
    charge_duration_min: number | null;
    max_power_kw: number | null;
    connector_type: string;
    station_status: string;
  }>;
  requires_user_action: boolean;
  applied_action: string | null;
  replanned_plan: PlanProposal | null;
  monitoring_events: MonitoringEvent[];
  agent_decisions: AgentDecision[];
  error_code: string | null;
};

