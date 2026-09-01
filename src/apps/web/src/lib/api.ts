import type {
  ApiErrorEnvelope,
  AssumptionSnapshot,
  AuthTokenResponse,
  AuthUser,
  LoginPayload,
  PlanGenerationResponse,
  PlanListResponse,
  PlaceAutocompleteResponse,
  PlaceDetailResponse,
  TripCreatePayload,
  TripCreatedResponse,
  RegisterPayload,
  UserVehicle,
  UserVehicleCreatePayload,
  VehicleProfileSnapshot,
  SimulationState,
  PlanDecisionResponse,
  ReplanningPlanDecisionResponse,
  ReplanningContextResponse,
  TripHistoryResponse,
  SimulationCatalog,
  SimulationRun,
  SimulationScenarioSelection,
} from "./types";
import { withPlanningStreamTimeout } from "./planningStreamWatchdog";
import { buildSimulationStartPayload } from "./simulationControls";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const LOCAL_TOKEN_KEY = "ev-route-access-token";
const SESSION_TOKEN_KEY = "ev-route-session-token";
const REQUEST_TIMEOUT_MS = 10000;

export function getAccessToken(): string | null {
  return localStorage.getItem(LOCAL_TOKEN_KEY) ?? sessionStorage.getItem(SESSION_TOKEN_KEY);
}

export function saveAccessToken(token: string, remember: boolean): void {
  localStorage.removeItem(LOCAL_TOKEN_KEY);
  sessionStorage.removeItem(SESSION_TOKEN_KEY);
  (remember ? localStorage : sessionStorage).setItem(
    remember ? LOCAL_TOKEN_KEY : SESSION_TOKEN_KEY,
    token,
  );
}

export function clearAccessToken(): void {
  localStorage.removeItem(LOCAL_TOKEN_KEY);
  sessionStorage.removeItem(SESSION_TOKEN_KEY);
}

function authenticatedHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = getAccessToken();
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
}

export class ApiError extends Error {
  readonly payload: ApiErrorEnvelope;
  readonly status: number;

  constructor(status: number, payload: ApiErrorEnvelope) {
    super(payload.error.message);
    this.status = status;
    this.payload = payload;
  }
}

async function parseApiResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const errorPayload = (await response.json()) as ApiErrorEnvelope;
    throw new ApiError(response.status, errorPayload);
  }
  return (await response.json()) as T;
}

export async function autocompletePlaces(
  input: string,
  sessionToken: string,
  signal?: AbortSignal,
): Promise<PlaceAutocompleteResponse> {
  const searchParams = new URLSearchParams({ input, session_token: sessionToken, limit: "8" });
  const response = await fetch(`${API_BASE_URL}/api/v1/places/autocomplete?${searchParams}`, { signal });
  return parseApiResponse<PlaceAutocompleteResponse>(response);
}

export async function getPlaceDetail(
  placeId: string,
  sessionToken: string,
  signal?: AbortSignal,
): Promise<PlaceDetailResponse> {
  const searchParams = new URLSearchParams({ place_id: placeId, session_token: sessionToken });
  const response = await fetch(`${API_BASE_URL}/api/v1/places/detail?${searchParams}`, { signal });
  return parseApiResponse<PlaceDetailResponse>(response);
}

export async function createTrip(payload: TripCreatePayload): Promise<TripCreatedResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/trips`, {
    method: "POST",
    headers: authenticatedHeaders({
      "Content-Type": "application/json",
    }),
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errorPayload = (await response.json()) as ApiErrorEnvelope;
    throw new ApiError(response.status, errorPayload);
  }

  return (await response.json()) as TripCreatedResponse;
}

export async function getCurrentAssumptions(vehicleProfileId: string): Promise<AssumptionSnapshot> {
  const searchParams = new URLSearchParams({ vehicle_profile_id: vehicleProfileId });
  const response = await fetch(`${API_BASE_URL}/api/v1/config/assumptions?${searchParams.toString()}`);

  if (!response.ok) {
    const errorPayload = (await response.json()) as ApiErrorEnvelope;
    throw new ApiError(response.status, errorPayload);
  }

  return (await response.json()) as AssumptionSnapshot;
}

export async function createTripPlan(tripId: string): Promise<PlanGenerationResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/trips/${tripId}/plans`, {
    method: "POST",
    headers: authenticatedHeaders({
      "Content-Type": "application/json",
    }),
  });

  if (!response.ok) {
    const errorPayload = (await response.json()) as ApiErrorEnvelope;
    throw new ApiError(response.status, errorPayload);
  }

  return (await response.json()) as PlanGenerationResponse;
}

export async function createTripPlanStream(
  tripId: string,
  onProgress: (message: string) => void,
  signal?: AbortSignal,
): Promise<PlanGenerationResponse> {
  const controller = new AbortController();
  const cancelFromCaller = () => controller.abort();
  signal?.addEventListener("abort", cancelFromCaller, { once: true });
  try {
  let response: Response;
  try {
    response = await withPlanningStreamTimeout(fetch(`${API_BASE_URL}/api/v1/trips/${tripId}/plans/stream`, {
      method: "POST",
      headers: authenticatedHeaders({ Accept: "text/event-stream" }),
      signal: controller.signal,
    }), 60_000, controller.signal);
  } catch (error) {
    controller.abort();
    throw signal?.aborted ? new Error("Đã hủy yêu cầu lập kế hoạch.") : error;
  }
  if (!response.ok || !response.body) return createTripPlan(tripId);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: PlanGenerationResponse | null = null;
  while (true) {
    let chunk: ReadableStreamReadResult<Uint8Array>;
    try {
      chunk = await withPlanningStreamTimeout(reader.read(), 60_000, controller.signal);
    } catch (error) {
      controller.abort();
      void reader.cancel();
      throw signal?.aborted ? new Error("Đã hủy yêu cầu lập kế hoạch.") : error;
    }
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true });
    const records = buffer.split("\n\n");
    buffer = records.pop() ?? "";
    for (const record of records) {
      const line = record.split("\n").find((item) => item.startsWith("data: "));
      if (!line) continue;
      const event = JSON.parse(line.slice(6)) as { type: string; message?: string; data?: PlanGenerationResponse };
      if (event.type === "progress" && event.message) onProgress(event.message);
      if (event.type === "result" && event.data) result = event.data;
      if (event.type === "error") throw new Error(event.message ?? "Không thể lập kế hoạch.");
    }
  }
  if (!result) throw new Error("Backend không trả về kết quả lập kế hoạch.");
  return result;
  } finally {
    signal?.removeEventListener("abort", cancelFromCaller);
  }
}

export async function getTripPlans(tripId: string): Promise<PlanListResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/trips/${tripId}/plans`, {
    headers: authenticatedHeaders(),
  });

  if (!response.ok) {
    const errorPayload = (await response.json()) as ApiErrorEnvelope;
    throw new ApiError(response.status, errorPayload);
  }

  return (await response.json()) as PlanListResponse;
}

export async function confirmTripPlan(planId: string, version: number): Promise<PlanDecisionResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/plans/${planId}/confirm`, {
    method: "POST",
    headers: authenticatedHeaders({ "If-Match": String(version) }),
  });
  return parseApiResponse<PlanDecisionResponse>(response);
}

export async function rejectTripPlan(
  planId: string,
  version: number,
  reason: string,
): Promise<PlanDecisionResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/plans/${planId}/reject`, {
    method: "POST",
    headers: authenticatedHeaders({
      "Content-Type": "application/json",
      "If-Match": String(version),
    }),
    body: JSON.stringify({ reason }),
  });
  return parseApiResponse<PlanDecisionResponse>(response);
}

export async function getReplanningContext(tripId: string): Promise<ReplanningContextResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/trips/${tripId}/context`, {
    headers: authenticatedHeaders(),
  });
  return parseApiResponse<ReplanningContextResponse>(response);
}

export async function listTripHistory(): Promise<TripHistoryResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/trips/history`, {
    headers: authenticatedHeaders(),
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  return parseApiResponse<TripHistoryResponse>(response);
}

export async function listSimulationCases(): Promise<SimulationCatalog> {
  const response = await fetch(`${API_BASE_URL}/api/v1/simulation-cases`, { headers: authenticatedHeaders() });
  return parseApiResponse<SimulationCatalog>(response);
}

export async function startSimulationCase(caseId: string, speedMultiplier: number): Promise<SimulationRun> {
  const response = await fetch(`${API_BASE_URL}/api/v1/simulation-runs`, {
    method: "POST", headers: authenticatedHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ case_id: caseId, speed_multiplier: speedMultiplier, idempotency_key: `${caseId}-${Date.now()}` }),
  });
  return parseApiResponse<SimulationRun>(response);
}

export async function controlSimulation(runId: string, operation: "step" | "pause" | "resume" | "reset" | "replan" | "refresh-telemetry"): Promise<SimulationRun> {
  const response = await fetch(`${API_BASE_URL}/api/v1/simulation-runs/${runId}/${operation}`, {
    method: "POST", headers: authenticatedHeaders(),
  });
  return parseApiResponse<SimulationRun>(response);
}

export async function replanTrip(tripId: string, state: SimulationState): Promise<PlanGenerationResponse> {
  if (!state.telemetry) throw new Error("Chưa có telemetry hiện tại để lập lại kế hoạch.");
  const response = await fetch(`${API_BASE_URL}/api/v1/trips/${tripId}/plans/replan`, {
    method: "POST", headers: authenticatedHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      current_lat: state.telemetry.lat, current_lon: state.telemetry.lon,
      current_soc_percent: state.telemetry.soc_percent,
      excluded_station_ids: state.unavailable_station_ids,
    }),
  });
  return parseApiResponse<PlanGenerationResponse>(response);
}

export async function submitF4Replan(
  tripId: string,
  state: SimulationState,
  canonicalEvents?: SimulationState["events"],
  onTrace?: (trace: import("./types").ReplanningOutcome["decision_trace"][number]) => void,
): Promise<import("./types").ReplanningOutcome> {
  if (!state.telemetry || state.events.length === 0) throw new Error("Chưa có event và telemetry để F4 đánh giá.");
  const telemetryId = state.telemetry.snapshot_id ?? `sim-${state.tick_count}`;
  const controller = new AbortController();
  let response: Response;
  try {
    response = await withPlanningStreamTimeout(fetch(`${API_BASE_URL}/api/v1/trips/${tripId}/replans/stream`, {
      method: "POST", headers: authenticatedHeaders({ "Content-Type": "application/json" }),
      signal: controller.signal,
      body: JSON.stringify({
        telemetry: { ...state.telemetry, snapshot_id: telemetryId },
        simulation_fault: state.simulation_fault,
        events: (canonicalEvents?.length ? canonicalEvents : state.events).map((event) => ({
          ...event,
          telemetry_snapshot_id: event.telemetry_snapshot_id ?? telemetryId,
          related_plan_version: event.related_plan_version ?? 0,
        })),
      }),
    }), 60_000, controller.signal);
  } catch (error) {
    controller.abort();
    throw error;
  }
  if (!response.ok) return parseApiResponse<import("./types").ReplanningOutcome>(response);
  if (!response.body) throw new Error("Máy chủ không mở được luồng phân tích trực tiếp.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let outcome: import("./types").ReplanningOutcome | null = null;
  while (true) {
    let chunk: ReadableStreamReadResult<Uint8Array>;
    try {
      chunk = await withPlanningStreamTimeout(reader.read(), 60_000, controller.signal);
    } catch (error) {
      controller.abort();
      void reader.cancel();
      throw error;
    }
    const { done, value } = chunk;
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line) as {
        type: "trace" | "complete" | "error";
        trace?: import("./types").ReplanningOutcome["decision_trace"][number];
        outcome?: import("./types").ReplanningOutcome;
        message?: string;
      };
      if (event.type === "trace" && event.trace) onTrace?.(event.trace);
      if (event.type === "complete" && event.outcome) outcome = event.outcome;
      if (event.type === "error") throw new Error(event.message || "Không thể phân tích lại hành trình.");
    }
    if (done) break;
  }
  if (!outcome) throw new Error("Luồng phân tích kết thúc nhưng không trả kết quả.");
  return outcome;
}

export async function confirmPlan(
  tripId: string,
  version: number,
  contextVersion: number,
): Promise<ReplanningPlanDecisionResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/trips/${tripId}/plans/${version}/confirm`, {
    method: "POST",
    headers: authenticatedHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      expected_plan_version: version,
      expected_context_version: contextVersion,
    }),
  });
  return parseApiResponse<ReplanningPlanDecisionResponse>(response);
}

export async function rejectReplanningPlan(
  tripId: string,
  version: number,
  contextVersion: number,
): Promise<ReplanningPlanDecisionResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/trips/${tripId}/plans/${version}/reject`, {
    method: "POST",
    headers: authenticatedHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      expected_plan_version: version,
      expected_context_version: contextVersion,
    }),
  });
  return parseApiResponse<ReplanningPlanDecisionResponse>(response);
}

export async function startSimulation(
  tripId: string,
  plan: import("./types").PlanProposal,
  scenario: SimulationScenarioSelection = "NORMAL",
  scenarioValue?: number,
  scenarioEvents?: import("./types").CompositeMonitoringEventType[],
  seed = 210,
  simulationFault: import("./types").SimulationFault = "NONE",
): Promise<SimulationState> {
  const response = await fetch(`${API_BASE_URL}/api/v1/simulator/trips/${tripId}/start`, {
    method: "POST", headers: authenticatedHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(buildSimulationStartPayload(
      plan, scenario, scenarioValue, scenarioEvents, seed, simulationFault,
    )),
  });
  return parseApiResponse<SimulationState>(response);
}

export async function getSimulatorCapabilities(): Promise<import("./types").SimulatorCapabilities> {
  const response = await fetch(`${API_BASE_URL}/api/v1/simulator/capabilities`, {
    headers: authenticatedHeaders(),
  });
  return parseApiResponse<import("./types").SimulatorCapabilities>(response);
}

export async function controlMonitoringSimulation(
  tripId: string,
  operation: "pause" | "resume" | "reset",
): Promise<SimulationState> {
  const response = await fetch(`${API_BASE_URL}/api/v1/simulator/trips/${tripId}/${operation}`, {
    method: "POST",
    headers: authenticatedHeaders(),
  });
  return parseApiResponse<SimulationState>(response);
}

export async function tickSimulation(tripId: string): Promise<SimulationState> {
  const response = await fetch(`${API_BASE_URL}/api/v1/simulator/trips/${tripId}/tick`, {
    method: "POST", headers: authenticatedHeaders(),
  });
  return parseApiResponse<SimulationState>(response);
}

export async function refreshSimulationTelemetry(tripId: string): Promise<SimulationState> {
  const response = await fetch(`${API_BASE_URL}/api/v1/simulator/trips/${tripId}/refresh-telemetry`, {
    method: "POST", headers: authenticatedHeaders(),
  });
  return parseApiResponse<SimulationState>(response);
}

export async function activateSimulationPlan(
  tripId: string,
  plan: import("./types").PlanProposal,
): Promise<SimulationState> {
  const response = await fetch(`${API_BASE_URL}/api/v1/simulator/trips/${tripId}/activate-plan`, {
    method: "POST",
    headers: authenticatedHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      plan_id: plan.plan_id,
      plan,
      scenario: "NORMAL",
      speed_multiplier: undefined,
    }),
  });
  return parseApiResponse<SimulationState>(response);
}

export async function decideSimulation(tripId: string, decision: "REQUEST_REPLAN" | "CONTINUE" | "STOP"): Promise<SimulationState> {
  const response = await fetch(`${API_BASE_URL}/api/v1/simulator/trips/${tripId}/decision`, {
    method: "POST", headers: authenticatedHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ decision }),
  });
  return parseApiResponse<SimulationState>(response);
}

export async function registerAccount(payload: RegisterPayload): Promise<AuthTokenResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse<AuthTokenResponse>(response);
}

export async function loginAccount(payload: LoginPayload): Promise<AuthTokenResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseApiResponse<AuthTokenResponse>(response);
}

export async function logoutAccount(): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/v1/auth/logout`, {
    method: "POST",
    headers: authenticatedHeaders(),
  });
  if (!response.ok && response.status !== 401) await parseApiResponse<never>(response);
  clearAccessToken();
}

export async function getCurrentUser(): Promise<AuthUser> {
  const response = await fetch(`${API_BASE_URL}/api/v1/auth/me`, {
    headers: authenticatedHeaders(),
  });
  return parseApiResponse<AuthUser>(response);
}

export async function listVehicleProfiles(): Promise<VehicleProfileSnapshot[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/vehicle-profiles`);
  const data = await parseApiResponse<{ profiles: VehicleProfileSnapshot[] }>(response);
  return data.profiles;
}

export async function listMyVehicles(): Promise<UserVehicle[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/me/vehicles`, {
    headers: authenticatedHeaders(),
  });
  const data = await parseApiResponse<{ vehicles: UserVehicle[] }>(response);
  return data.vehicles;
}

export async function addMyVehicle(payload: UserVehicleCreatePayload): Promise<UserVehicle> {
  const response = await fetch(`${API_BASE_URL}/api/v1/me/vehicles`, {
    method: "POST",
    headers: authenticatedHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  return parseApiResponse<UserVehicle>(response);
}

export async function setDefaultVehicle(vehicleId: string): Promise<UserVehicle[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/me/vehicles/${vehicleId}/default`, {
    method: "PATCH",
    headers: authenticatedHeaders(),
  });
  const data = await parseApiResponse<{ vehicles: UserVehicle[] }>(response);
  return data.vehicles;
}

