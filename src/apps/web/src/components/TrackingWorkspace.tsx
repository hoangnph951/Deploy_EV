import { useEffect, useMemo, useState } from "react";

import { ApiError, controlSimulation, listSimulationCases, startSimulationCase } from "../lib/api";
import type {
  PlaceSelection,
  PlanProposal,
  SimulationCatalog,
  SimulationRun,
} from "../lib/types";
import { SocChart } from "./SocChart";
import { TripPlanMap } from "./TripPlanMap";

const PROFILE_LABELS: Record<string, string> = {
  NORMAL: "Bình thường",
  ROUTE_DEVIATION: "Lệch tuyến",
  SOC_UNDERPERFORMANCE: "SOC thấp hơn dự kiến",
  STATION_UNAVAILABLE: "Trạm không khả dụng",
  STALE_TELEMETRY: "Dữ liệu xe đã cũ",
  NO_FEASIBLE_ALTERNATIVE: "Không còn phương án an toàn",
};

const EVENT_LABELS: Record<string, string> = {
  ROUTE_DEVIATION: "Xe lệch khỏi lộ trình",
  SOC_UNDERPERFORMANCE: "Mức pin thấp hơn dự kiến",
  STATION_UNAVAILABLE: "Trạm sạc không khả dụng",
  STALE_TELEMETRY: "Dữ liệu GPS và mức pin đã cũ",
};

const INTENT_LABELS: Record<string, string> = {
  ROUTE_RECOVERY: "Khôi phục lộ trình",
  ENERGY_RESCUE: "Bảo đảm an toàn năng lượng",
  STATION_SUBSTITUTION: "Tìm trạm sạc thay thế",
  TELEMETRY_RECOVERY: "Cập nhật dữ liệu xe",
};

const TOOL_LABELS: Record<string, string> = {
  request_telemetry_refresh: "Yêu cầu GPS và mức pin mới",
  route_from_current_position: "Tính tuyến từ vị trí hiện tại",
  nearest_station_reachability: "Kiểm tra khả năng đến trạm gần nhất",
  station_search: "Tìm trạm sạc phù hợp",
  energy_simulation: "Tính mức tiêu thụ và pin dự phòng",
  feasibility_check: "Kiểm tra tính khả thi và an toàn",
  compare_plans: "So sánh với lộ trình hiện tại",
};

type PublicTraceStep = {
  title: string;
  detail: string;
  tone?: "warning" | "success";
};

type Props = {
  plan: PlanProposal | null;
  origin: PlaceSelection | null;
  destination: PlaceSelection | null;
  initialSoc: number;
  run: SimulationRun | null;
  onRunChange: (run: SimulationRun | null) => void;
};

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "Không thể thực hiện mô phỏng.";
}

export function TrackingWorkspace({ plan, origin, destination, initialSoc, run, onRunChange }: Props) {
  const [catalog, setCatalog] = useState<SimulationCatalog | null>(null);
  const [baseCaseId, setBaseCaseId] = useState("");
  const [profile, setProfile] = useState("NORMAL");
  const [speed, setSpeed] = useState(10);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [visibleTraceSteps, setVisibleTraceSteps] = useState(0);
  const [pendingAction, setPendingAction] = useState<"replan" | "refresh-telemetry" | null>(null);
  const [actionNotice, setActionNotice] = useState("");

  function updateRun(nextRun: SimulationRun) {
    onRunChange(
      run?.run_id === nextRun.run_id
        ? {
            ...nextRun,
            route_polyline: nextRun.applied_action !== run.applied_action
              ? nextRun.route_polyline
              : run.route_polyline,
            original_route_polyline: run.original_route_polyline,
            charging_stations: nextRun.applied_action !== run.applied_action
              ? nextRun.charging_stations
              : run.charging_stations,
            monitoring_events: run.monitoring_events.length === nextRun.monitoring_events.length
              ? run.monitoring_events
              : nextRun.monitoring_events,
          }
        : nextRun,
    );
  }

  useEffect(() => {
    void listSimulationCases()
      .then((result) => {
        setCatalog(result);
        const firstReady = result.cases.find((item) => item.readiness === "READY");
        setBaseCaseId((current) => current || firstReady?.base_case_id || "");
        setProfile(firstReady?.profile ?? "NORMAL");
      })
      .catch((reason: unknown) => setError(errorMessage(reason)));
  }, []);

  useEffect(() => {
    if (!run || run.status !== "RUNNING" || busy) return;
    const timer = window.setTimeout(() => {
      setBusy(true);
      void controlSimulation(run.run_id, "step")
        .then(updateRun)
        .catch((reason: unknown) => setError(errorMessage(reason)))
        .finally(() => setBusy(false));
    }, Math.max(250, 2000 / run.speed_multiplier));
    return () => window.clearTimeout(timer);
  }, [busy, onRunChange, run]);

  const baseCases = useMemo(() => {
    const unique = new Map<string, SimulationCatalog["cases"][number]>();
    catalog?.cases.forEach((item) => {
      if (!unique.has(item.base_case_id)) unique.set(item.base_case_id, item);
    });
    return [...unique.values()];
  }, [catalog]);
  const profileCases = useMemo(
    () => catalog?.cases.filter((item) => item.base_case_id === baseCaseId) ?? [],
    [baseCaseId, catalog],
  );
  const selectedCase = useMemo(
    () => profileCases.find((item) => item.profile === profile) ?? profileCases[0] ?? null,
    [profile, profileCases],
  );
  const caseId = selectedCase?.case_id ?? "";
  const telemetry = run?.telemetry;
  const mapTelemetry = telemetry ? {
    lat: telemetry.lat,
    lon: telemetry.lng,
    soc_percent: telemetry.actual_soc_percent,
    expected_soc_percent: telemetry.expected_soc_percent,
    speed_kph: 0,
    distance_km: 0,
    progress_percent: telemetry.progress_percent,
    source: "SIMULATED" as const,
    freshness: telemetry.age_seconds > 60 ? "STALE" as const : "FRESH" as const,
    recorded_at: run?.updated_at ?? new Date().toISOString(),
  } : null;
  const latestEvent = run?.monitoring_events[run.monitoring_events.length - 1] ?? null;
  const latestDecision = run?.agent_decisions[run.agent_decisions.length - 1] ?? null;
  const unavailableStationIds = useMemo(
    () => run?.monitoring_events.flatMap((event) => event.station_id ? [event.station_id] : []) ?? [],
    [run?.monitoring_events],
  );
  const vehicleName = run
    ? `${run.case.origin_name} → ${run.case.destination_name}`
    : selectedCase
      ? `${selectedCase.origin_name} → ${selectedCase.destination_name}`
      : "Chuyến đi đang theo dõi";
  const actualSoc = telemetry?.actual_soc_percent ?? selectedCase?.initial_soc_percent ?? initialSoc;
  const expectedSoc = telemetry?.expected_soc_percent ?? selectedCase?.initial_soc_percent ?? initialSoc;
  const delta = actualSoc - expectedSoc;
  const progress = run ? Math.round(((run.current_tick + 1) / run.total_ticks) * 100) : 0;
  const awaitingAction = run?.status === "AWAITING_ACTION";
  const noFeasibleReplan = latestDecision?.action === "NO_FEASIBLE_PLAN_REQUEST_ASSISTANCE";
  const telemetryRecoveryDecision = latestDecision?.action === "REQUEST_NEW_TELEMETRY";
  const staleTelemetry = Boolean(awaitingAction && telemetryRecoveryDecision);
  const userActionLabel = latestDecision?.action === "REQUEST_NEW_TELEMETRY"
    ? "Yêu cầu dữ liệu xe mới"
    : "Lập lại kế hoạch";
  const eventLabel = latestEvent ? EVENT_LABELS[latestEvent.event_type] ?? latestEvent.event_type : "Chưa có cảnh báo";
  const decisionSummary = telemetryRecoveryDecision
    ? staleTelemetry
      ? "Dữ liệu GPS và mức pin đã quá hạn. Trợ lý dừng việc tính tuyến và đề nghị lấy dữ liệu xe mới."
      : "GPS và mức pin mới đã được tiếp nhận. Xe tiếp tục lộ trình hiện tại mà không tạo tuyến thay thế."
    : noFeasibleReplan
      ? "Chưa chứng minh được một lộ trình thay thế an toàn. Cần hỗ trợ vận hành trước khi tiếp tục."
      : latestDecision?.intent === "ROUTE_RECOVERY"
      ? "Xe đã lệch khỏi lộ trình. Trợ lý đề nghị tính lại tuyến từ vị trí và mức pin hiện tại."
      : latestDecision?.intent === "ENERGY_RESCUE"
        ? "Mức pin thực tế thấp hơn dự kiến. Trợ lý ưu tiên kiểm tra khả năng đến trạm sạc an toàn."
        : latestDecision?.intent === "STATION_SUBSTITUTION"
          ? "Trạm sạc dự kiến không còn khả dụng. Trợ lý đề nghị tìm trạm thay thế và so sánh lộ trình."
          : "Trợ lý đã kiểm tra dữ liệu hiện tại và chuẩn bị hành động phù hợp.";
  const publicTrace = useMemo<PublicTraceStep[]>(() => {
    if (!latestDecision || !latestEvent) return [];
    const steps: PublicTraceStep[] = [
      {
        title: "Đã tiếp nhận cảnh báo",
        detail: `${EVENT_LABELS[latestEvent.event_type] ?? latestEvent.event_type} tại vị trí ${telemetry?.lat.toFixed(4) ?? "—"}, ${telemetry?.lng.toFixed(4) ?? "—"}.`,
      },
      {
        title: "Đã kiểm tra dữ liệu đầu vào",
        detail: telemetryRecoveryDecision
          ? "Mẫu GPS và mức pin gây cảnh báo đã cũ hơn 60 giây, không đủ điều kiện để tính lại lộ trình."
          : `GPS và mức pin còn hiệu lực; SOC hiện tại là ${actualSoc.toFixed(1)}%.`,
        tone: telemetryRecoveryDecision ? "warning" : "success",
      },
      ...latestDecision.selected_tools.map((tool) => ({
        title: TOOL_LABELS[tool] ?? "Thực hiện bước kiểm tra nghiệp vụ",
        detail: tool === "request_telemetry_refresh"
          ? "Chỉ yêu cầu một mẫu GPS/SOC mới; không tạo tuyến thay thế từ dữ liệu cũ."
          : "Kết quả của bước này được đưa vào kiểm tra an toàn trước khi đề xuất.",
      })),
      {
        title: "Đã kiểm tra quy tắc an toàn",
        detail: telemetryRecoveryDecision
          ? "Đã chặn mọi thao tác lập lại kế hoạch cho đến khi có GPS và mức pin mới."
          : latestDecision.action_guard === "PASSED"
            ? "Đề xuất đáp ứng các điều kiện an toàn và vẫn cần người dùng xác nhận."
            : "Đề xuất tự động đã bị chặn; hệ thống chuyển sang phương án thận trọng.",
        tone: latestDecision.action_guard === "PASSED" && !telemetryRecoveryDecision ? "success" : "warning",
      },
      {
        title: "Hành động đề xuất",
        detail: telemetryRecoveryDecision
          ? staleTelemetry
            ? "Yêu cầu dữ liệu xe mới. Khi nhận được GPS/SOC hợp lệ, xe tiếp tục lộ trình hiện tại."
            : "Đã nhận dữ liệu xe mới và tiếp tục lộ trình hiện tại."
          : "Chờ người dùng xác nhận trước khi lập và áp dụng lộ trình thay thế.",
      },
    ];
    return steps;
  }, [actualSoc, latestDecision, latestEvent, staleTelemetry, telemetry, telemetryRecoveryDecision]);

  useEffect(() => {
    if (!latestDecision) {
      setVisibleTraceSteps(0);
      return;
    }
    setVisibleTraceSteps(1);
    const timer = window.setInterval(() => {
      setVisibleTraceSteps((current) => {
        if (current >= publicTrace.length) {
          window.clearInterval(timer);
          return current;
        }
        return current + 1;
      });
    }, 420);
    return () => window.clearInterval(timer);
  }, [latestDecision?.agent_run_id, publicTrace.length]);

  async function begin() {
    if (!selectedCase) return;
    setBusy(true);
    setError("");
    setActionNotice("");
    try {
      updateRun(await startSimulationCase(selectedCase.case_id, speed));
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 404) {
        try {
          const refreshed = await listSimulationCases();
          setCatalog(refreshed);
          const replacement = refreshed.cases.find((item) =>
            item.origin_name === selectedCase.origin_name
            && item.destination_name === selectedCase.destination_name
            && item.initial_soc_percent === selectedCase.initial_soc_percent
            && item.profile === selectedCase.profile
            && item.readiness === "READY"
          );
          if (!replacement) throw reason;
          setBaseCaseId(replacement.base_case_id);
          setProfile(replacement.profile);
          updateRun(await startSimulationCase(replacement.case_id, speed));
        } catch (refreshError) {
          setError(errorMessage(refreshError));
        }
      } else {
        setError(errorMessage(reason));
      }
    } finally {
      setBusy(false);
    }
  }

  async function control(operation: "pause" | "resume" | "reset" | "replan" | "refresh-telemetry") {
    if (!run) return;
    setBusy(true);
    setError("");
    try {
      const nextRun = await controlSimulation(run.run_id, operation);
      updateRun(nextRun);
      if (operation === "refresh-telemetry") {
        setActionNotice("Đã nhận GPS và mức pin mới. Xe đang tiếp tục lộ trình hiện tại.");
      } else if (operation === "replan") {
        setActionNotice("Đã lập lại kế hoạch từ vị trí hiện tại và tiếp tục sau xác nhận của bạn.");
      }
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
      setPendingAction(null);
    }
  }

  function requestAction() {
    if (!latestDecision || noFeasibleReplan) return;
    setPendingAction(latestDecision.action === "REQUEST_NEW_TELEMETRY" ? "refresh-telemetry" : "replan");
  }

  return (
    <main className="tracking-page" id="top">
      <section className="tracking-toolbar">
        <div>
          <p className="tracking-kicker">GIÁM SÁT CHUYẾN ĐI</p>
          <h1>Theo dõi lộ trình</h1>
          <p>Dữ liệu xe mô phỏng · phát hiện sự kiện · trợ lý phân tích và đề xuất xử lý</p>
        </div>
        <div className="tracking-run-summary">
          <div className="tracking-run-status">
            <span className={`status-dot ${run?.status === "RUNNING" ? "is-live" : ""}`} />
            {run ? (
              run.status === "RUNNING" ? "Đang di chuyển"
                : run.status === "PAUSED" ? "Đang tạm dừng"
                  : run.status === "AWAITING_ACTION" ? "Đang chờ xử lý sự cố"
                    : "Đã kết thúc"
            ) : "Chưa chạy"}
          </div>
          {catalog ? <small>{catalog.ready_case_count}/{catalog.target_case_count} case sẵn sàng</small> : null}
        </div>
      </section>

      {awaitingAction && latestEvent && latestDecision ? (
        <section className="tracking-incident-banner" role="alert" aria-live="assertive">
          <div className="tracking-incident-icon">!</div>
          <div>
            <p>PHÁT HIỆN SỰ CỐ · XE ĐÃ TẠM DỪNG</p>
            <h2>{eventLabel}</h2>
            <span>{decisionSummary}</span>
            <small>Giá trị {latestEvent.actual_value ?? "—"} · Ngưỡng {latestEvent.threshold_value ?? "—"} · Tick {latestEvent.tick}</small>
          </div>
          <button
            type="button"
            disabled={busy || noFeasibleReplan}
            onClick={requestAction}
          >
            {noFeasibleReplan ? "Không có phương án an toàn" : userActionLabel}
          </button>
        </section>
      ) : null}

      <section className="tracking-layout">
        <aside className="tracking-sidebar">
          <article className="tracking-control-card">
            <p className="tracking-card-label">KỊCH BẢN MÔ PHỎNG</p>
            <label>
              <span>Chuyến đi</span>
              <select
                value={baseCaseId}
                onChange={(event) => {
                  const nextBaseCaseId = event.target.value;
                  setBaseCaseId(nextBaseCaseId);
                  const nextProfiles = catalog?.cases.filter((item) => item.base_case_id === nextBaseCaseId) ?? [];
                  if (!nextProfiles.some((item) => item.profile === profile && item.readiness === "READY")) {
                    setProfile(nextProfiles.find((item) => item.readiness === "READY")?.profile ?? "NORMAL");
                  }
                  onRunChange(null);
                }}
              >
                {baseCases.map((item) => (
                  <option key={item.base_case_id} value={item.base_case_id}>
                    {item.origin_name} → {item.destination_name} · SOC {item.initial_soc_percent}%
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Tình huống</span>
              <select value={selectedCase?.profile ?? profile} onChange={(event) => { setProfile(event.target.value); onRunChange(null); }}>
                {profileCases.map((item) => (
                  <option key={item.profile} value={item.profile} disabled={item.readiness !== "READY"}>
                    {PROFILE_LABELS[item.profile]}
                  </option>
                ))}
              </select>
            </label>
            <div className="tracking-control-row">
              <label>
                <span>Tốc độ</span>
                <select value={speed} onChange={(event) => setSpeed(Number(event.target.value))}>
                  {[1, 5, 10, 20, 50].map((value) => <option key={value} value={value}>x{value}</option>)}
                </select>
              </label>
              <button type="button" className="tracking-start-button" disabled={!caseId || busy || awaitingAction} onClick={() => { void begin(); }}>
                Chạy
              </button>
            </div>
            {run ? (
              <div className="tracking-run-controls">
                {run.status === "RUNNING" ? (
                  <button type="button" disabled={busy} onClick={() => { void control("pause"); }}>Tạm dừng</button>
                ) : run.status === "PAUSED" ? (
                  <button type="button" disabled={busy} onClick={() => { void control("resume"); }}>Tiếp tục</button>
                ) : null}
                <button type="button" disabled={busy} onClick={() => { void control("reset"); }}>Đặt lại</button>
                <span>Tick {run.current_tick + 1}/{run.total_ticks}</span>
              </div>
            ) : null}
            {run ? <div className="tracking-progress"><span style={{ width: `${progress}%` }} /></div> : null}
            {error ? <small className="tracking-control-error" role="alert">{error}</small> : null}
          </article>

          <article className="tracking-vehicle-card">
            <span className="tracking-icon">EV</span>
            <div>
              <strong>{vehicleName}</strong>
              <small>{run?.case.provider ?? selectedCase?.provider ?? "Chưa chọn dữ liệu"}</small>
            </div>
          </article>
          <article className="tracking-soc-card">
            <div className="tracking-card-label">SOC hiện tại <span>● {telemetry ? (telemetry.age_seconds > 60 ? "Dữ liệu cũ" : "Dữ liệu mới") : "Chờ dữ liệu"}</span></div>
            <strong>{actualSoc.toFixed(0)}%</strong>
            <div className="soc-bar"><span style={{ width: `${Math.max(0, Math.min(100, actualSoc))}%` }} /></div>
            <div className="tracking-soc-meta"><span>Dự kiến {expectedSoc.toFixed(0)}%</span><b className={delta < 0 ? "negative" : "positive"}>{delta > 0 ? "+" : ""}{delta.toFixed(1)}%</b></div>
          </article>
          <article className="tracking-metrics">
            <div><span>TIẾN ĐỘ</span><strong>{telemetry?.progress_percent ?? 0}%</strong></div>
            <div><span>LỆCH TUYẾN</span><strong>{telemetry?.distance_to_route_km ?? 0} km</strong></div>
            <div><span>CẬP NHẬT</span><strong>{telemetry ? `${telemetry.age_seconds}s` : "—"}</strong></div>
          </article>
          <div className="tracking-provenance">
            <span>⌖</span><small>GPS<br /><b>MÔ PHỎNG</b></small>
            <span>ϟ</span><small>SOC<br /><b>MÔ PHỎNG</b></small>
            <span>▥</span><small>DỮ LIỆU<br /><b>{telemetry && telemetry.age_seconds > 60 ? "CŨ" : "MỚI"}</b></small>
          </div>
        </aside>

        <section className="tracking-map-column">
          <TripPlanMap
            plan={run ? null : plan}
            origin={run ? null : origin}
            destination={run ? null : destination}
            telemetry={mapTelemetry}
          />
          <div className="tracking-map-caption"><span className="tracking-live-dot" /> {telemetry ? `Xe đang ở tick ${telemetry.tick} · ${telemetry.lat.toFixed(4)}, ${telemetry.lng.toFixed(4)}` : "Bản đồ sẽ hiển thị vị trí xe khi mô phỏng bắt đầu"}</div>
        </section>

        <aside className="tracking-insights">
          <article className="tracking-status-card">
            <p className="tracking-card-label">TRẠNG THÁI CHUYẾN ĐI</p>
            <h2><span className="status-check">{awaitingAction ? "!" : "✓"}</span>{awaitingAction ? "Đang chờ bạn xử lý" : run?.applied_action ? "Đang chạy theo lộ trình mới" : "Đang bám sát kế hoạch"}</h2>
            <p>{awaitingAction && latestEvent ? eventLabel : actionNotice || (run?.applied_action ? "Lộ trình mới đã được áp dụng sau xác nhận của bạn." : "Chưa phát hiện rủi ro cần lập lại kế hoạch.")}</p>
          </article>
          {plan && !run ? <SocChart plan={plan} initialSoc={initialSoc} /> : (
            <article className="tracking-empty-card"><strong>SOC thực tế / dự kiến</strong><p>{telemetry ? `${actualSoc.toFixed(1)}% / ${expectedSoc.toFixed(1)}% tại ${telemetry.progress_percent}% hành trình.` : "Bắt đầu mô phỏng để xem diễn biến SOC."}</p></article>
          )}
          <article className={`tracking-next-card ${latestEvent ? "has-alert" : ""}`}>
            <p className="tracking-card-label">SỰ KIỆN GẦN NHẤT</p>
            {latestEvent ? <><strong>{eventLabel}</strong><span>{latestEvent.actual_value ?? "—"} · ngưỡng {latestEvent.threshold_value ?? "—"}</span></> : <><strong>Không có cảnh báo</strong><span>Tiếp tục theo kế hoạch hiện tại</span></>}
          </article>
          <article className={`tracking-ai-card ${staleTelemetry ? "has-stale-data" : ""}`}>
            <div className="ai-card-heading"><span className="ai-spark">✦</span><div><p className="tracking-card-label">TRỢ LÝ ĐIỀU PHỐI HÀNH TRÌNH</p><h2>{latestDecision ? (visibleTraceSteps < publicTrace.length ? "Đang hiển thị quá trình phân tích" : "Đã hoàn tất phân tích") : "Đang chờ sự kiện"}</h2></div><span className={`ai-live-state ${latestDecision ? "is-active" : ""}`}>{latestDecision ? "TRỰC TIẾP" : "SẴN SÀNG"}</span></div>
            {latestDecision ? <>
              <section className="ai-location-block" aria-label="Vị trí và độ mới dữ liệu xe">
                <div><span>Vị trí hiện tại</span><strong>{telemetry ? `${telemetry.lat.toFixed(4)}, ${telemetry.lng.toFixed(4)}` : "Chưa có dữ liệu"}</strong></div>
                <div className={staleTelemetry ? "is-stale" : "is-fresh"}><span>{staleTelemetry ? "!" : "✓"}</span><strong>{staleTelemetry ? "Dữ liệu xe đã cũ" : "Dữ liệu xe còn hiệu lực"}</strong></div>
                <p>{staleTelemetry ? "Đang chờ GPS và mức pin mới..." : `SOC hiện tại ${actualSoc.toFixed(1)}% · cập nhật ${telemetry?.age_seconds.toFixed(0) ?? 0} giây trước`}</p>
              </section>
              <div className="ai-intent">{INTENT_LABELS[latestDecision.intent] ?? "Xử lý sự kiện hành trình"}</div>
              <p className="ai-explanation">{decisionSummary}</p>
              <ol className="tracking-thought-stream" aria-live="polite" aria-label="Nhật ký phân tích trực tiếp của trợ lý">
                {publicTrace.slice(0, visibleTraceSteps).map((step, index) => (
                  <li className={step.tone ? `is-${step.tone}` : ""} key={`${step.title}-${index}`}>
                    <span className="thought-step-index">{index + 1}</span>
                    <div><strong>{step.title}</strong><p>{step.detail}</p></div>
                    <span className="thought-step-state">{index === visibleTraceSteps - 1 && visibleTraceSteps < publicTrace.length ? "Đang xử lý" : "Hoàn tất"}</span>
                  </li>
                ))}
              </ol>
              {run?.replanned_plan ? <div className="ai-plan-result"><span>Lộ trình thay thế đã kiểm tra</span><strong>{run.replanned_plan.route.distance_km.toFixed(1)} km · SOC đích {run.replanned_plan.final_arrival_soc_percent.toFixed(1)}%</strong><p>{run.replanned_plan.charging_stops.length ? `Trạm sạc: ${run.replanned_plan.charging_stops.map((stop) => stop.name).join(" → ")}` : "Không cần dừng sạc"}</p></div> : null}
            </> : <p>Trợ lý sẽ hiển thị lần lượt các bước kiểm tra dữ liệu, ràng buộc an toàn và hành động đề xuất khi phát hiện biến cố.</p>}
          </article>
          {latestDecision ? <section className={`tracking-recommended-action ${awaitingAction ? "is-alert" : ""}`}>
            <span>Hành động đề xuất</span>
            <strong>{telemetryRecoveryDecision ? (staleTelemetry ? "Yêu cầu dữ liệu xe mới" : "Dữ liệu xe đã được cập nhật") : noFeasibleReplan ? "Yêu cầu hỗ trợ vận hành" : "Lập lại kế hoạch từ vị trí hiện tại"}</strong>
            <p>{telemetryRecoveryDecision ? (staleTelemetry ? "Cần GPS và SOC mới trước khi đánh giá lại. Lộ trình hiện tại được giữ nguyên." : "GPS và SOC mới đã hợp lệ. Xe đang tiếp tục đúng lộ trình trước đó.") : decisionSummary}</p>
            {awaitingAction && !noFeasibleReplan ? <button type="button" disabled={busy} onClick={requestAction}>{userActionLabel}</button> : null}
          </section> : <div className="tracking-action">Không cần lập lại kế hoạch</div>}
        </aside>
      </section>

      {pendingAction ? <div className="tracking-confirm-backdrop" role="presentation" onMouseDown={() => !busy && setPendingAction(null)}>
        <section className="tracking-confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="tracking-confirm-title" onMouseDown={(event) => event.stopPropagation()}>
          <button className="tracking-confirm-close" type="button" aria-label="Đóng" disabled={busy} onClick={() => setPendingAction(null)}>×</button>
          <span className="tracking-confirm-icon">{pendingAction === "refresh-telemetry" ? "⌖" : "↻"}</span>
          <p className="tracking-card-label">XÁC NHẬN HÀNH ĐỘNG</p>
          <h2 id="tracking-confirm-title">{pendingAction === "refresh-telemetry" ? "Yêu cầu GPS và mức pin mới?" : "Lập lại kế hoạch hành trình?"}</h2>
          <p>{pendingAction === "refresh-telemetry"
            ? "Hệ thống sẽ yêu cầu một mẫu GPS/SOC mới. Không lập lại tuyến từ dữ liệu cũ; khi dữ liệu hợp lệ, xe tiếp tục lộ trình hiện tại."
            : "Hệ thống sẽ dùng GPS và SOC hiện tại để tạo lộ trình thay thế, kiểm tra an toàn rồi mới áp dụng."}</p>
          <div className="tracking-confirm-facts">
            <span>Vị trí <strong>{telemetry ? `${telemetry.lat.toFixed(4)}, ${telemetry.lng.toFixed(4)}` : "—"}</strong></span>
            <span>Mức pin <strong>{telemetry ? `${telemetry.actual_soc_percent.toFixed(1)}%` : "—"}</strong></span>
            <span>Lộ trình hiện tại <strong>{pendingAction === "refresh-telemetry" ? "Giữ nguyên" : "Chỉ đổi sau kiểm tra"}</strong></span>
          </div>
          <div className="tracking-confirm-actions">
            <button type="button" disabled={busy} onClick={() => setPendingAction(null)}>Quay lại</button>
            <button type="button" className="is-primary" disabled={busy} onClick={() => { void control(pendingAction); }}>{busy ? "Đang xử lý..." : "Xác nhận yêu cầu"}</button>
          </div>
        </section>
      </div> : null}
    </main>
  );
}
