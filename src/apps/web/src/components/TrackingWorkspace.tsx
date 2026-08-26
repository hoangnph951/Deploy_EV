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
  STALE_TELEMETRY: "Telemetry quá cũ",
  NO_FEASIBLE_ALTERNATIVE: "Không còn phương án an toàn",
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
  const userActionLabel = latestDecision?.action === "REQUEST_NEW_TELEMETRY"
    ? "Yêu cầu telemetry mới"
    : "Lập lại kế hoạch";

  async function begin() {
    if (!selectedCase) return;
    setBusy(true);
    setError("");
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
      updateRun(await controlSimulation(run.run_id, operation));
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="tracking-page" id="top">
      <section className="tracking-toolbar">
        <div>
          <p className="tracking-kicker">GIÁM SÁT CHUYẾN ĐI</p>
          <h1>Theo dõi lộ trình</h1>
          <p>Telemetry mô phỏng · phát hiện sự kiện · AI Agent phân tích và đề xuất xử lý</p>
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
            <h2>{latestEvent.event_type.replace(/_/g, " ")}</h2>
            <span>{latestDecision.explanation}</span>
            <small>Giá trị {latestEvent.actual_value ?? "—"} · Ngưỡng {latestEvent.threshold_value ?? "—"} · Tick {latestEvent.tick}</small>
          </div>
          <button
            type="button"
            disabled={busy || noFeasibleReplan}
            onClick={() => { void control(latestDecision.action === "REQUEST_NEW_TELEMETRY" ? "refresh-telemetry" : "replan"); }}
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
            <div className="tracking-card-label">SOC hiện tại <span>● {telemetry ? "Dữ liệu mới" : "Chờ telemetry"}</span></div>
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
            <h2><span className="status-check">{awaitingAction ? "!" : "✓"}</span>{awaitingAction ? "Đang chờ bạn xử lý" : run?.applied_action ? "Đang chạy theo plan mới" : "Đang bám sát kế hoạch"}</h2>
            <p>{awaitingAction && latestEvent ? latestEvent.event_type.replace(/_/g, " ") : run?.applied_action ? "Candidate plan đã được áp dụng sau xác nhận của người dùng." : "Chưa phát hiện rủi ro cần tái lập kế hoạch."}</p>
          </article>
          {plan && !run ? <SocChart plan={plan} initialSoc={initialSoc} /> : (
            <article className="tracking-empty-card"><strong>SOC thực tế / dự kiến</strong><p>{telemetry ? `${actualSoc.toFixed(1)}% / ${expectedSoc.toFixed(1)}% tại ${telemetry.progress_percent}% hành trình.` : "Bắt đầu mô phỏng để xem diễn biến SOC."}</p></article>
          )}
          <article className={`tracking-next-card ${latestEvent ? "has-alert" : ""}`}>
            <p className="tracking-card-label">SỰ KIỆN GẦN NHẤT</p>
            {latestEvent ? <><strong>{latestEvent.event_type.replace(/_/g, " ")}</strong><span>{latestEvent.actual_value ?? "—"} · ngưỡng {latestEvent.threshold_value ?? "—"}</span></> : <><strong>Không có cảnh báo</strong><span>Tiếp tục theo kế hoạch hiện tại</span></>}
          </article>
          <article className="tracking-ai-card">
            <div className="ai-card-heading"><span className="ai-spark">✦</span><div><p className="tracking-card-label">AI AGENT 1 · REPLANNING SUPERVISOR</p><h2>{latestDecision ? "Supervisor đã phân tích xong" : "Supervisor đang chờ sự kiện"}</h2></div></div>
            {latestDecision ? <>
              <div className="ai-intent">{latestDecision.intent}</div>
              <div className="ai-source">{latestDecision.classification_source === "AI_AGENT" ? "OpenAI đã chọn hướng xử lý" : "Fallback policy đang điều phối"} · confidence {(latestDecision.intent_confidence * 100).toFixed(0)}%</div>
              <p>{latestDecision.explanation}</p>
              <dl className="tracking-agent-trace">
                <div><dt>Chiến lược</dt><dd>{latestDecision.strategy}</dd></div>
                <div><dt>Tools</dt><dd>{latestDecision.selected_tools.join(" → ")}</dd></div>
                <div><dt>Safety gate</dt><dd>{latestDecision.action_guard}</dd></div>
                <div><dt>So sánh plan</dt><dd>{latestDecision.plan_diff?.summary ?? "Không tạo candidate plan."}</dd></div>
                {run?.replanned_plan ? <div><dt>F1 realtime candidate</dt><dd>{run.replanned_plan.route.provider} · {run.replanned_plan.route.distance_km.toFixed(1)} km · SOC đích {run.replanned_plan.final_arrival_soc_percent.toFixed(1)}% · {run.replanned_plan.charging_stops.length ? `Trạm mới: ${run.replanned_plan.charging_stops.map((stop) => stop.name).join(" → ")}` : "Không cần dừng sạc"}</dd></div> : null}
              </dl>
            </> : <p>Agent sẽ phân loại intent, chọn tool, kiểm tra plan diff và đề xuất hành động khi phát hiện biến cố.</p>}
          </article>
          <div className={`tracking-action ${awaitingAction ? "is-alert" : ""}`}>{run?.applied_action ? `ĐÃ ÁP DỤNG · ${run.applied_action}` : latestDecision?.action ?? "Không cần tái lập kế hoạch"}</div>
        </aside>
      </section>
    </main>
  );
}
