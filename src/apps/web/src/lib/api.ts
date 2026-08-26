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
  TripHistoryResponse,
  SimulationCatalog,
  SimulationRun,
} from "./types";

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
): Promise<PlanGenerationResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/trips/${tripId}/plans/stream`, {
    method: "POST",
    headers: authenticatedHeaders({ Accept: "text/event-stream" }),
  });
  if (!response.ok || !response.body) return createTripPlan(tripId);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: PlanGenerationResponse | null = null;
  while (true) {
    const chunk = await reader.read();
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

export async function startSimulation(tripId: string, plan: import("./types").PlanProposal): Promise<SimulationState> {
  const response = await fetch(`${API_BASE_URL}/api/v1/simulator/trips/${tripId}/start`, {
    method: "POST", headers: authenticatedHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ plan_id: plan.plan_id, plan, seed: Date.now(), scenario: "RANDOM", unhappy_probability: 0.35 }),
  });
  return parseApiResponse<SimulationState>(response);
}

export async function tickSimulation(tripId: string): Promise<SimulationState> {
  const response = await fetch(`${API_BASE_URL}/api/v1/simulator/trips/${tripId}/tick`, {
    method: "POST", headers: authenticatedHeaders(),
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

