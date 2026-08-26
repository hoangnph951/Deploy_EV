import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { DataTrustPanel, ProposalSummary, VehicleSpecs, WhyThisPlan } from "./components/DashboardPanels";
import { AuthPage } from "./components/AuthPage";
import { GoongPlaceInput } from "./components/GoongPlaceInput";
import { InfeasibleWarningBanner } from "./components/InfeasibleWarningBanner";
import { RecoveryPanel } from "./components/RecoveryPanel";
import { SocChart } from "./components/SocChart";
import { TripPlanMap } from "./components/TripPlanMap";
import { TripMonitoringDashboard } from "./components/TripMonitoringDashboard";
import { TripHistoryPage } from "./components/TripHistoryPage";
import { VehicleSetup } from "./components/VehicleSetup";
import {
  ApiError,
  confirmTripPlan,
  clearAccessToken,
  createTrip,
  createTripPlan,
  createTripPlanStream,
  getAccessToken,
  getCurrentAssumptions,
  getCurrentUser,
  listMyVehicles,
  listTripHistory,
  listVehicleProfiles,
  logoutAccount,
  setDefaultVehicle,
  replanTrip,
} from "./lib/api";
import type {
  AmbiguousCandidate,
  AssumptionSnapshot,
  AuthTokenResponse,
  AuthUser,
  PlaceSelection,
  NoFeasiblePlan,
  PlanProposal,
  PlanningRecoveryResponse,
  RecoveryOption,
  TripCreatePayload,
  UserVehicle,
  VehicleProfileSnapshot,
  SimulationState,
  TripHistoryItem,
} from "./lib/types";

const formSchema = z.object({
  originAddress: z.string().min(1, "Vui lòng nhập điểm xuất phát."),
  destinationAddress: z.string().min(1, "Vui lòng nhập điểm đến."),
  initialSocPercent: z.coerce
    .number()
    .min(1, "SOC phải từ 1%.")
    .max(100, "SOC không vượt quá 100%."),
});

type FormValues = z.infer<typeof formSchema>;
type ResolutionState = {
  field: "origin" | "destination";
  candidates: AmbiguousCandidate[];
  payload: TripCreatePayload;
};

export type PlanningStep = {
  id: string;
  label: string;
  detail: string;
  status: "pending" | "running" | "done" | "error";
};

const INITIAL_PLANNING_STEPS: PlanningStep[] = [
  { id: "route", label: "Xác định tuyến đường", detail: "Đang lấy tuyến thực tế từ Goong", status: "pending" },
  { id: "stations", label: "Tìm trạm sạc phù hợp", detail: "Đang quét trạm dọc hành trình và kiểm tra cổng sạc", status: "pending" },
  { id: "soc", label: "Mô phỏng năng lượng", detail: "Đang tính SOC theo từng chặng và thời gian sạc", status: "pending" },
  { id: "verify", label: "Kiểm tra an toàn", detail: "Đang xác minh các chặng và mức dự phòng", status: "pending" },
  { id: "proposal", label: "Xếp hạng phương án", detail: "Đang chọn phương án phù hợp nhất", status: "pending" },
];

function buildPayload(
  values: FormValues,
  origin: PlaceSelection,
  destination: PlaceSelection,
  vehicleProfileId: string,
): TripCreatePayload {
  return {
    origin: {
      address: origin.address,
      lat: origin.lat,
      lng: origin.lng,
      source_type: "REAL_API",
    },
    destination: {
      address: destination.address,
      lat: destination.lat,
      lng: destination.lng,
      source_type: "REAL_API",
    },
    initial_soc_percent: values.initialSocPercent,
    soc_source_type: "MANUAL",
    vehicle_profile_id: vehicleProfileId,
    preference: "balanced",
  };
}

function applyResolution(
  payload: TripCreatePayload,
  field: "origin" | "destination",
  candidate: AmbiguousCandidate,
): TripCreatePayload {
  return {
    ...payload,
    [field]: { address: null, lat: candidate.lat, lng: candidate.lng, source_type: "MANUAL" },
  };
}

export default function App() {
  const [activeTab, setActiveTab] = useState<"planning" | "tracking" | "history">("planning");
  const [authLoading, setAuthLoading] = useState(true);
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);
  const [vehicleProfiles, setVehicleProfiles] = useState<VehicleProfileSnapshot[]>([]);
  const [userVehicles, setUserVehicles] = useState<UserVehicle[]>([]);
  const [selectedVehicleId, setSelectedVehicleId] = useState("");
  const [showVehicleSetup, setShowVehicleSetup] = useState(false);
  const [assumptions, setAssumptions] = useState<AssumptionSnapshot | null>(null);
  const [assumptionsLoading, setAssumptionsLoading] = useState(true);
  const [assumptionsError, setAssumptionsError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [noFeasiblePlan, setNoFeasiblePlan] = useState<NoFeasiblePlan | null>(null);
  const [recoveryResult, setRecoveryResult] = useState<PlanningRecoveryResponse | null>(null);
  const [planningLoading, setPlanningLoading] = useState(false);
  const [inlineError, setInlineError] = useState("");
  const [warningMessage, setWarningMessage] = useState("");
  const [currentTripId, setCurrentTripId] = useState("");
  const [planProposal, setPlanProposal] = useState<PlanProposal | null>(null);
  const [planAlternatives, setPlanAlternatives] = useState<PlanProposal[]>([]);
  const [resolutionState, setResolutionState] = useState<ResolutionState | null>(null);
  const [originPlace, setOriginPlace] = useState<PlaceSelection | null>(null);
  const [destinationPlace, setDestinationPlace] = useState<PlaceSelection | null>(null);
  const [planningMessage, setPlanningMessage] = useState("");
  const [simulationState, setSimulationState] = useState<SimulationState | null>(null);
  const [tripHistory, setTripHistory] = useState<TripHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [choosingJourney, setChoosingJourney] = useState(false);

  const {
    register,
    setValue,
    watch,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: { originAddress: "", destinationAddress: "", initialSocPercent: 60 },
  });

  const originAddress = watch("originAddress");
  const destinationAddress = watch("destinationAddress");
  const initialSocPercent = watch("initialSocPercent");

  const selectedVehicle = userVehicles.find((vehicle) => vehicle.id === selectedVehicleId)
    ?? userVehicles.find((vehicle) => vehicle.is_default)
    ?? userVehicles[0]
    ?? null;

  useEffect(() => {
    let active = true;
    const bootstrap = async () => {
      try {
        const profiles = await listVehicleProfiles();
        if (active) setVehicleProfiles(profiles);
        if (!getAccessToken()) return;
        const [user, vehicles] = await Promise.all([getCurrentUser(), listMyVehicles()]);
        if (!active) return;
        setCurrentUser(user);
        setUserVehicles(vehicles);
        setSelectedVehicleId((vehicles.find((vehicle) => vehicle.is_default) ?? vehicles[0])?.id ?? "");
      } catch {
        clearAccessToken();
        if (active) {
          setCurrentUser(null);
          setUserVehicles([]);
        }
      } finally {
        if (active) setAuthLoading(false);
      }
    };
    void bootstrap();
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!selectedVehicle) {
      setAssumptions(null);
      setAssumptionsLoading(false);
      return;
    }
    let active = true;
    setAssumptionsLoading(true);
    getCurrentAssumptions(selectedVehicle.vehicle_profile.id)
      .then((snapshot) => {
        if (active) {
          setAssumptions(snapshot);
          setAssumptionsError("");
        }
      })
      .catch(() => {
        if (active) setAssumptionsError("Không tải được cấu hình giả định từ backend.");
      })
      .finally(() => {
        if (active) setAssumptionsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [selectedVehicle?.vehicle_profile.id]);

  const handleAuthenticated = async (result: AuthTokenResponse) => {
    setCurrentUser(result.user);
    const [profiles, vehicles] = await Promise.all([listVehicleProfiles(), listMyVehicles()]);
    setVehicleProfiles(profiles);
    setUserVehicles(vehicles);
    setSelectedVehicleId((vehicles.find((vehicle) => vehicle.is_default) ?? vehicles[0])?.id ?? "");
    setShowVehicleSetup(result.needs_vehicle_setup || vehicles.length === 0);
  };

  const handleVehicleCreated = (vehicle: UserVehicle) => {
    setUserVehicles((vehicles) => [
      ...vehicles.map((item) => ({ ...item, is_default: false })),
      vehicle,
    ]);
    setSelectedVehicleId(vehicle.id);
    setShowVehicleSetup(false);
  };

  const changeVehicle = async (vehicleId: string) => {
    setSelectedVehicleId(vehicleId);
    try {
      const vehicles = await setDefaultVehicle(vehicleId);
      setUserVehicles(vehicles);
    } catch {
      setInlineError("Không thể đổi xe mặc định lúc này.");
    }
  };

  const signOut = async () => {
    try { await logoutAccount(); } finally {
      clearAccessToken();
      setCurrentUser(null);
      setUserVehicles([]);
      setSelectedVehicleId("");
      setPlanProposal(null);
      setPlanAlternatives([]);
      setNoFeasiblePlan(null);
      setRecoveryResult(null);
      setTripHistory([]);
    }
  };

  const loadTripHistory = async () => {
    setHistoryLoading(true);
    setHistoryError("");
    try {
      const response = await listTripHistory();
      setTripHistory(response.trips);
    } catch (error) {
      setHistoryError(error instanceof ApiError
        ? error.payload.error.message
        : error instanceof DOMException && error.name === "TimeoutError"
          ? "Máy chủ không phản hồi khi tải lịch sử. Vui lòng thử lại."
          : "Không thể tải lịch sử hành trình.");
    } finally {
      setHistoryLoading(false);
    }
  };

  const openHistory = () => {
    setActiveTab("history");
    void loadTripHistory();
  };

  const chooseJourney = async (selectedPlan: PlanProposal) => {
    setChoosingJourney(true);
    setInlineError("");
    try {
      const response = await confirmTripPlan(selectedPlan.plan_id, selectedPlan.version);
      setPlanProposal(response.plan);
      setPlanAlternatives((plans) => plans.map((plan) => plan.plan_id === response.plan.plan_id ? response.plan : plan));
      setSimulationState(null);
      setActiveTab("tracking");
    } catch (error) {
      setInlineError(error instanceof ApiError ? error.payload.error.message : "Không thể lưu hành trình đã chọn.");
    } finally {
      setChoosingJourney(false);
    }
  };

  const generatePlan = async (tripId: string) => {
    setPlanningLoading(true);
    setPlanningMessage("Đang khởi động agent lập kế hoạch…");
    setInlineError("");
    try {
      const response = await createTripPlanStream(tripId, setPlanningMessage);
      if (response.outcome === "PROVEN_INFEASIBLE") {
        setPlanProposal(null);
        setPlanAlternatives([]);
        setNoFeasiblePlan(response);
        setRecoveryResult(null);
      } else if (response.outcome === "ACTION_REQUIRED" || response.outcome === "SEARCH_EXHAUSTED") {
        setPlanProposal(null);
        setPlanAlternatives([]);
        setNoFeasiblePlan(null);
        setRecoveryResult(response);
      } else if (response.outcome === "CONDITIONAL") {
        setNoFeasiblePlan(null);
        setRecoveryResult(response);
        setPlanProposal(response.plan);
        setPlanAlternatives(response.alternatives?.length ? response.alternatives : [response.plan]);
      } else {
        setNoFeasiblePlan(null);
        setRecoveryResult(null);
        setPlanProposal(response.plan);
        setPlanAlternatives(response.alternatives?.length ? response.alternatives : [response.plan]);
      }
    } catch (error) {
      setPlanningMessage("Agent không thể hoàn tất kế hoạch.");
      setInlineError(
        error instanceof ApiError
          ? error.payload.error.message
          : "Không thể lập kế hoạch lúc này. Vui lòng thử lại.",
      );
    } finally {
      setPlanningLoading(false);
    }
  };

  const generateReplan = async () => {
    if (!simulationState) return;
    setPlanningLoading(true);
    try {
      const response = await replanTrip(currentTripId, simulationState);
      if (response.outcome === "PLAN_CREATED" || response.outcome === "CONDITIONAL") {
        setPlanProposal(response.plan);
        setPlanAlternatives(response.alternatives?.length ? response.alternatives : [response.plan]);
      } else if (response.outcome === "PROVEN_INFEASIBLE") setNoFeasiblePlan(response);
      else setRecoveryResult(response);
    } finally { setPlanningLoading(false); }
  };

  const submitTrip = async (payload: TripCreatePayload) => {
    setSubmitting(true);
    setPlanningMessage("Đang chuẩn bị dữ liệu chuyến đi…");
    setInlineError("");
    setPlanProposal(null);
    setPlanAlternatives([]);
    setNoFeasiblePlan(null);
    setRecoveryResult(null);
    try {
      const response = await createTrip(payload);
      setResolutionState(null);
      setAssumptions(response.assumptions);
      setCurrentTripId(response.trip_id);
      await generatePlan(response.trip_id);
    } catch (error) {
      setPlanningMessage("Không thể chuẩn bị dữ liệu chuyến đi.");
      if (error instanceof ApiError && error.payload.error.code === "AMBIGUOUS_LOCATION") {
        setResolutionState({
          field: (error.payload.error.details?.field as "origin" | "destination") ?? "origin",
          candidates: error.payload.error.details?.candidates ?? [],
          payload,
        });
      } else if (error instanceof ApiError) {
        const validation = error.payload.error.details?.errors?.[0]?.msg;
        setInlineError(validation ?? error.payload.error.message);
      } else {
        setInlineError("Không thể gửi yêu cầu. Vui lòng kiểm tra kết nối backend.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  const onSubmit = handleSubmit(async (values) => {
    if (!originPlace || !destinationPlace) {
      setInlineError("Hãy chọn cả điểm xuất phát và điểm đến từ danh sách gợi ý của Goong.");
      return;
    }
    if (!selectedVehicle) {
      setInlineError("Hãy thiết lập xe trước khi lập kế hoạch.");
      return;
    }
    setWarningMessage(
      values.initialSocPercent < 20
        ? "SOC dưới 20%. Hệ thống vẫn tính nhưng rủi ro có thể tăng đáng kể."
        : "",
    );
    await submitTrip(buildPayload(values, originPlace, destinationPlace, selectedVehicle.vehicle_profile.id));
  });

  const useCurrentLocation = () => {
    if (!navigator.geolocation) {
      setInlineError("Trình duyệt này không hỗ trợ lấy vị trí hiện tại.");
      return;
    }
    setInlineError("");
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        const selection: PlaceSelection = {
          address: `Vị trí hiện tại (${coords.latitude.toFixed(5)}, ${coords.longitude.toFixed(5)})`,
          lat: coords.latitude,
          lng: coords.longitude,
          placeId: null,
        };
        setOriginPlace(selection);
        setValue("originAddress", selection.address, { shouldValidate: true });
      },
      () => setInlineError("Không lấy được vị trí hiện tại. Hãy cấp quyền vị trí hoặc chọn từ Goong."),
      { enableHighAccuracy: true, timeout: 10000 },
    );
  };

  const swapPlaces = () => {
    const nextOrigin = destinationPlace;
    const nextDestination = originPlace;
    setOriginPlace(nextOrigin);
    setDestinationPlace(nextDestination);
    setValue("originAddress", nextOrigin?.address ?? "", { shouldValidate: true });
    setValue("destinationAddress", nextDestination?.address ?? "", { shouldValidate: true });
  };

  const applyRecoveryEndpoint = (option: RecoveryOption) => {
    if (option.lat == null || option.lng == null) return;
    const selection: PlaceSelection = {
      address: option.title,
      lat: option.lat,
      lng: option.lng,
      placeId: null,
    };
    setDestinationPlace(selection);
    setValue("destinationAddress", selection.address, { shouldValidate: true });
    setCurrentTripId("");
    setRecoveryResult(null);
  };

  if (authLoading) {
    return <main className="app-loading"><span>ϟ</span><strong>Đang mở VGo…</strong></main>;
  }
  if (!currentUser) return <AuthPage onAuthenticated={(result) => { void handleAuthenticated(result); }} />;
  if (showVehicleSetup || userVehicles.length === 0) {
    return <VehicleSetup profiles={vehicleProfiles} canCancel={userVehicles.length > 0} onComplete={handleVehicleCreated} onCancel={() => setShowVehicleSetup(false)} />;
  }

  return (
    <main className="ev-dashboard">
      <header className="app-topbar">
        <a className="brand" href="#top" aria-label="VGo - Lập kế hoạch"><img src="/logo.png" alt="VGo" /></a>
        <nav aria-label="Điều hướng chính">
          <button type="button" className={`nav-item ${activeTab === "planning" ? "nav-item--active" : ""}`} onClick={() => setActiveTab("planning")}>▣ <strong>Lập kế hoạch</strong></button>
          <button type="button" className={`nav-item ${activeTab === "tracking" ? "nav-item--active" : ""}`} disabled={!planProposal} title={!planProposal ? "Hãy lập kế hoạch trước" : "Theo dõi hành trình"} onClick={() => setActiveTab("tracking")}>▢ <strong>Theo dõi</strong>{planProposal ? <span className="nav-ready-dot" /> : null}</button>
          <button type="button" className={`nav-item ${activeTab === "history" ? "nav-item--active" : ""}`} onClick={openHistory}>◷ <strong>Lịch sử</strong></button>
          <span className="nav-item">? Hỗ trợ</span>
        </nav>
        <div className="account-actions">
          <button type="button" onClick={() => setShowVehicleSetup(true)}>+ Thêm xe</button>
          <span className="user-badge" aria-label={currentUser.full_name}>{currentUser.full_name.slice(0, 2).toUpperCase()}</span>
          <button type="button" onClick={() => { void signOut(); }}>Đăng xuất</button>
        </div>
      </header>

      {activeTab === "planning" ? <>
      <section className="dashboard-workspace" id="top">
        <aside className="journey-panel dashboard-card">
          <div className="dashboard-card-title">
            <div><small>Thiết lập chuyến đi</small><h2>Hành trình</h2></div>
          </div>
          <form className="trip-form" onSubmit={onSubmit}>
            <div className="goong-route-picker">
              <div className="route-picker-rail" aria-hidden="true">
                <span className="route-dot" />
                <span className="route-line" />
                <span className="route-pin">●</span>
              </div>
              <div className="route-picker-fields">
                <label className="route-picker-label" htmlFor="origin-goong-place">
                  <span>Điểm xuất phát</span>
                  <GoongPlaceInput
                    id="origin-goong-place"
                    value={originAddress}
                    placeholder="Chọn điểm bắt đầu"
                    onTextChange={(address) => {
                      setValue("originAddress", address, { shouldValidate: true });
                      if (address !== originPlace?.address) setOriginPlace(null);
                    }}
                    onPlaceSelect={(place) => {
                      setOriginPlace(place);
                      setValue("originAddress", place.address, { shouldValidate: true });
                    }}
                  />
                  <input type="hidden" {...register("originAddress")} />
                  {errors.originAddress ? <small className="field-error">{errors.originAddress.message}</small> : null}
                </label>
                <label className="route-picker-label" htmlFor="destination-goong-place">
                  <span>Điểm đến</span>
                  <GoongPlaceInput
                    id="destination-goong-place"
                    value={destinationAddress}
                    placeholder="Chọn điểm đến"
                    onTextChange={(address) => {
                      setValue("destinationAddress", address, { shouldValidate: true });
                      if (address !== destinationPlace?.address) setDestinationPlace(null);
                    }}
                    onPlaceSelect={(place) => {
                      setDestinationPlace(place);
                      setValue("destinationAddress", place.address, { shouldValidate: true });
                    }}
                  />
                  <input type="hidden" {...register("destinationAddress")} />
                  {errors.destinationAddress ? <small className="field-error">{errors.destinationAddress.message}</small> : null}
                </label>
              </div>
              <div className="route-picker-actions">
                <button type="button" className="map-icon-button" onClick={swapPlaces} title="Đảo chiều hành trình">⇅</button>
                <button type="button" className="map-icon-button" onClick={useCurrentLocation} title="Dùng vị trí hiện tại">◎</button>
              </div>
            </div>

            <label className="garage-selector">
              <span>Xe dùng cho hành trình</span>
              <select value={selectedVehicle?.id ?? ""} onChange={(event) => { void changeVehicle(event.target.value); }}>
                {userVehicles.map((vehicle) => <option key={vehicle.id} value={vehicle.id}>{vehicle.nickname || vehicle.vehicle_profile.name}{vehicle.license_plate ? ` · ${vehicle.license_plate}` : ""}</option>)}
              </select>
            </label>
            <VehicleSpecs assumptions={assumptions} />
            {assumptionsLoading ? <small className="subtle-status">Đang đồng bộ profile xe…</small> : null}
            {assumptionsError ? <div className="message-banner error">{assumptionsError}</div> : null}

            <label className="soc-control">
              <span><strong>SOC ban đầu</strong><output>{Number(initialSocPercent) || 0}%</output></span>
              <input
                className="soc-slider"
                type="range"
                min={1}
                max={100}
                value={Number(initialSocPercent) || 1}
                onChange={(event) => setValue("initialSocPercent", Number(event.target.value), { shouldValidate: true })}
              />
              <span className="soc-scale"><small>1%</small><small>50%</small><small>100%</small></span>
              <input className="visually-hidden" type="number" min={1} max={100} {...register("initialSocPercent")} />
              {errors.initialSocPercent ? <small className="field-error">{errors.initialSocPercent.message}</small> : null}
            </label>
            <div className="reserve-chip">♢ Dự phòng {assumptions?.reserve_soc_percent ?? 15}%</div>

            {warningMessage ? <div className="message-banner warning">{warningMessage}</div> : null}
            {inlineError ? <div className="message-banner error">{inlineError}</div> : null}

            <button className="primary-button" type="submit" disabled={submitting || planningLoading}>
              {submitting || planningLoading ? "Đang tính dữ liệu live…" : "✦ Lập kế hoạch"}
            </button>
            {currentTripId ? (
              <button className="recalculate-button" type="button" disabled={planningLoading} onClick={() => generatePlan(currentTripId)}>
                Tính lại với dữ liệu mới nhất
              </button>
            ) : null}
          </form>
        </aside>

        <section className="map-workspace">
          <TripPlanMap plan={planProposal} origin={originPlace} destination={destinationPlace} />
        </section>

        <ProposalSummary
          plan={planProposal}
          alternatives={planAlternatives}
          onSelectPlan={setPlanProposal}
          reserveSoc={planProposal?.assumptions.reserve_soc_percent ?? assumptions?.reserve_soc_percent ?? 15}
          loading={planningLoading || submitting}
          planningMessage={planningMessage}
          onChooseJourney={(selectedPlan) => { if (!choosingJourney) void chooseJourney(selectedPlan); }}
        />
      </section>

      {planProposal ? (
        <section className="dashboard-lower-grid">
          <SocChart plan={planProposal} initialSoc={Number(initialSocPercent) || 60} />
          <DataTrustPanel plan={planProposal} />
          <WhyThisPlan plan={planProposal} />
        </section>
      ) : null}

      {noFeasiblePlan ? (
        <section className="infeasible-section"><InfeasibleWarningBanner result={noFeasiblePlan} /></section>
      ) : null}

      {recoveryResult ? (
        <section className="infeasible-section">
          <RecoveryPanel result={recoveryResult} onApplyEndpoint={applyRecoveryEndpoint} />
        </section>
      ) : null}
      </> : activeTab === "tracking" ? (
        <section className="tracking-page" id="top">
          {planProposal ? <>
            <header className="tracking-page-header">
              <div><small>F3 · GIÁM SÁT HÀNH TRÌNH</small><h1>Theo dõi chuyến đi</h1><p>PLAN v{planProposal.version} · Dữ liệu xe trong phiên này được mô phỏng.</p></div>
              <button type="button" onClick={() => setActiveTab("planning")}>← Xem lại kế hoạch</button>
            </header>
            <div className="tracking-grid">
              <section className="tracking-map"><TripPlanMap plan={planProposal} origin={originPlace} destination={destinationPlace} telemetry={simulationState?.telemetry} /></section>
              <TripMonitoringDashboard tripId={currentTripId} plan={planProposal} onRequestReplan={generateReplan} onStateChange={setSimulationState} />
            </div>
          </> : <div className="tracking-empty"><span>⌁</span><h2>Chưa có hành trình để theo dõi</h2><p>Hãy lập và chọn một kế hoạch trước khi bắt đầu mô phỏng.</p><button type="button" onClick={() => setActiveTab("planning")}>Đi tới lập kế hoạch</button></div>}
        </section>
      ) : <TripHistoryPage trips={tripHistory} loading={historyLoading} error={historyError} onRetry={() => { void loadTripHistory(); }} />}

      {resolutionState ? (
        <div className="modal-backdrop" role="presentation">
          <div className="modal-card" role="dialog" aria-modal="true" aria-labelledby="ambiguous-title">
            <p className="panel-kicker">Cần xác nhận địa điểm</p>
            <h3 id="ambiguous-title">
              {resolutionState.field === "origin" ? "Điểm xuất phát" : "Điểm đến"} đang mơ hồ
            </h3>
            <p>Chọn đúng địa điểm để hệ thống không tự đoán.</p>
            <div className="candidate-list">
              {resolutionState.candidates.map((candidate) => (
                <button
                  key={`${candidate.label}-${candidate.lat}-${candidate.lng}`}
                  className="candidate-item"
                  type="button"
                  onClick={() => {
                    const next = applyResolution(resolutionState.payload, resolutionState.field, candidate);
                    setResolutionState(null);
                    void submitTrip(next);
                  }}
                >
                  <strong>{candidate.label}</strong>
                  <span>{candidate.lat.toFixed(4)}, {candidate.lng.toFixed(4)}</span>
                </button>
              ))}
            </div>
            <button className="ghost-button" type="button" onClick={() => setResolutionState(null)}>
              Đóng và sửa lại địa chỉ
            </button>
          </div>
        </div>
      ) : null}
    </main>
  );
}
