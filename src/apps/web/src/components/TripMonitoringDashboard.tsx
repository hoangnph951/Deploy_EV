import { useEffect, useRef, useState } from "react";

import {
  activateSimulationPlan,
  controlMonitoringSimulation,
  decideSimulation,
  getSimulatorCapabilities,
  refreshSimulationTelemetry,
  startSimulation,
  tickSimulation,
} from "../lib/api";
import {
  activeSnapshotEvents,
  canonicalEventBatchKey,
  ReplanningSubmissionGuard,
} from "../lib/replanningSubmission";
import {
  completeF4Confirmation,
  completeF4Rejection,
  getConfirmableF4Plan,
  isPendingF4Plan,
} from "../lib/f4Confirmation";
import { labelStatus, traceHeading } from "../lib/replanningPresentation";
import type {
  CompositeMonitoringEventType,
  PlanProposal,
  ReplanningOutcome,
  SimulationFault,
  SimulationScenarioSelection,
  SimulationState,
} from "../lib/types";
import { ReplanningSupervisorPanel } from "./ReplanningSupervisorPanel";

type CanonicalEvent = SimulationState["events"][number];
const SCENARIO_OPTIONS: Array<{ value: SimulationScenarioSelection; label: string }> = [
  { value: "NORMAL", label: "Bình thường · không phát sự cố" },
  { value: "ROUTE_DEVIATION", label: "Xe lệch khỏi tuyến" },
  { value: "SOC_UNDERPERFORMANCE", label: "SOC thấp hơn dự kiến" },
  { value: "STATION_UNAVAILABLE", label: "Trạm sạc không khả dụng" },
  { value: "STALE_TELEMETRY", label: "GPS và SOC đã cũ" },
  { value: "MULTI_EVENT", label: "Lệch tuyến + SOC + trạm cùng lúc" },
  { value: "RANDOM", label: "Ngẫu nhiên · 50% có sự cố" },
];
const SCENARIO_VALUE_CONFIG: Partial<Record<SimulationScenarioSelection, {
  label: string;
  defaultValue: number;
  step: number;
  presets: number[];
}>> = {
  ROUTE_DEVIATION: { label: "Khoảng cách lệch tuyến (km)", defaultValue: 2.01, step: 0.01, presets: [1.99, 2, 2.01] },
  SOC_UNDERPERFORMANCE: { label: "Mức SOC thấp hơn dự kiến (%)", defaultValue: 5.1, step: 0.1, presets: [4.9, 5, 5.1] },
  STALE_TELEMETRY: { label: "Tuổi dữ liệu telemetry (giây)", defaultValue: 61, step: 1, presets: [60, 61] },
};
const COMPOSITE_EVENT_OPTIONS: Array<{ value: CompositeMonitoringEventType; label: string }> = [
  { value: "ROUTE_DEVIATION", label: "Lệch tuyến" },
  { value: "SOC_UNDERPERFORMANCE", label: "Lệch SOC" },
  { value: "STATION_UNAVAILABLE", label: "Trạm không khả dụng" },
];
type Props = {
  tripId: string;
  plan: PlanProposal;
  planConfirmed: boolean;
  onCanonicalEvent: (
    state: SimulationState,
    events: CanonicalEvent[],
    onTrace: (trace: ReplanningOutcome["decision_trace"][number]) => void,
  ) => Promise<ReplanningOutcome>;
  onConfirmPlan: (plan: PlanProposal) => Promise<boolean>;
  onRejectPlan: (plan: PlanProposal) => Promise<boolean>;
  confirmingPlan?: boolean;
  onStateChange?: (state: SimulationState) => void;
};

export function TripMonitoringDashboard({
  tripId, plan, planConfirmed, onCanonicalEvent, onConfirmPlan, onRejectPlan,
  confirmingPlan = false, onStateChange,
}: Props) {
  const [state, setState] = useState<SimulationState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [f4Run, setF4Run] = useState<ReplanningOutcome | null>(null);
  const [confirmedReplacementPlanId, setConfirmedReplacementPlanId] = useState("");
  const [rejectedReplacementPlanId, setRejectedReplacementPlanId] = useState("");
  const [failedEvents, setFailedEvents] = useState<CanonicalEvent[]>([]);
  const [rejectingPlan, setRejectingPlan] = useState(false);
  const [liveTrace, setLiveTrace] = useState<ReplanningOutcome["decision_trace"]>([]);
  const [recoveryNotice, setRecoveryNotice] = useState("");
  const [refreshingTelemetry, setRefreshingTelemetry] = useState(false);
  const [selectedScenario, setSelectedScenario] = useState<SimulationScenarioSelection>("NORMAL");
  const [scenarioValue, setScenarioValue] = useState(2.01);
  const [simulationSeed, setSimulationSeed] = useState(210);
  const [simulationFault, setSimulationFault] = useState<SimulationFault>("NONE");
  const [faultInjectionEnabled, setFaultInjectionEnabled] = useState(false);
  const [compositeEvents, setCompositeEvents] = useState<CompositeMonitoringEventType[]>([
    "ROUTE_DEVIATION", "SOC_UNDERPERFORMANCE", "STATION_UNAVAILABLE",
  ]);
  const [safetyWarning, setSafetyWarning] = useState("");
  const submissionGuard = useRef(new ReplanningSubmissionGuard());

  useEffect(() => {
    submissionGuard.current.reset();
    setF4Run(null);
    setConfirmedReplacementPlanId("");
    setRejectedReplacementPlanId("");
    setFailedEvents([]);
    setSelectedScenario("NORMAL");
    setScenarioValue(2.01);
    setSimulationSeed(210);
    setSimulationFault("NONE");
    setSafetyWarning("");
  }, [tripId]);

  useEffect(() => {
    let active = true;
    getSimulatorCapabilities()
      .then((capabilities) => {
        if (active) setFaultInjectionEnabled(capabilities.fault_injection_enabled);
      })
      .catch(() => {
        if (active) setFaultInjectionEnabled(false);
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (
      !plan.charging_stops.length
      && (selectedScenario === "STATION_UNAVAILABLE"
        || (selectedScenario === "MULTI_EVENT" && compositeEvents.includes("STATION_UNAVAILABLE")))
    ) {
      if (selectedScenario === "STATION_UNAVAILABLE") setSelectedScenario("NORMAL");
    }
    if (!plan.charging_stops.length && compositeEvents.includes("STATION_UNAVAILABLE")) {
      setCompositeEvents(["ROUTE_DEVIATION", "SOC_UNDERPERFORMANCE"]);
    }
  }, [plan.plan_id, plan.charging_stops.length, selectedScenario]);

  useEffect(() => { if (state) onStateChange?.(state); }, [onStateChange, state]);

  useEffect(() => {
    if (state?.status !== "RUNNING") return;
    const timer = window.setInterval(() => {
      tickSimulation(tripId).then(setState).catch((reason) => setError(
        reason instanceof Error ? reason.message : "Mất kết nối với bộ mô phỏng.",
      ));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [state?.status, tripId]);

  const start = async () => {
    setBusy(true); setError(""); setRecoveryNotice(""); setSafetyWarning("");
    try {
      submissionGuard.current.reset();
      setF4Run(null);
      setRejectedReplacementPlanId("");
      setFailedEvents([]);
      setState(await startSimulation(
        tripId,
        plan,
        selectedScenario,
        SCENARIO_VALUE_CONFIG[selectedScenario] ? scenarioValue : undefined,
        selectedScenario === "MULTI_EVENT" ? compositeEvents : undefined,
        simulationSeed,
        simulationFault,
      ));
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Không thể bắt đầu mô phỏng."); }
    finally { setBusy(false); }
  };

  const control = async (operation: "pause" | "resume" | "reset") => {
    setBusy(true); setError(""); setRecoveryNotice("");
    try {
      if (operation === "reset") {
        submissionGuard.current.reset();
        setF4Run(null);
        setLiveTrace([]);
        setFailedEvents([]);
      }
      setState(await controlMonitoringSimulation(tripId, operation));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể điều khiển mô phỏng.");
    } finally {
      setBusy(false);
    }
  };

  const decide = async (decision: "CONTINUE" | "STOP") => {
    setBusy(true);
    try { setState(await decideSimulation(tripId, decision)); }
    finally { setBusy(false); }
  };

  const submitCanonicalEvents = async (current: SimulationState, events: CanonicalEvent[]) => {
    if (!current.telemetry || events.length === 0) return;
    const telemetrySnapshotId = current.telemetry.snapshot_id ?? `sim-${current.tick_count}`;
    const key = canonicalEventBatchKey(
      tripId,
      telemetrySnapshotId,
      events.map((event) => event.event_id),
    );
    if (!submissionGuard.current.begin(key)) return;
    setBusy(true); setError(""); setRecoveryNotice(""); setFailedEvents([]);
    setLiveTrace([]);
    try {
      const run = await onCanonicalEvent(current, events, (trace) => {
        setLiveTrace((items) => (
          items.some((item) => item.sequence === trace.sequence) ? items : [...items, trace]
        ));
      });
      setF4Run(run);
      setConfirmedReplacementPlanId("");
      setRejectedReplacementPlanId("");
      if (["INSUFFICIENT_EVIDENCE", "SEARCH_EXHAUSTED"].includes(run.status)) {
        submissionGuard.current.fail(key);
        setFailedEvents(events);
      } else {
        submissionGuard.current.complete(key);
      }
    } catch (reason) {
      submissionGuard.current.fail(key);
      setFailedEvents(events);
      setError(reason instanceof Error ? reason.message : "Không thể phân tích sự kiện hành trình.");
    } finally { setBusy(false); }
  };

  const confirmReplacementPlan = async (replacement: PlanProposal) => {
    setError("");
    try {
      const confirmed = await onConfirmPlan(replacement);
      if (!confirmed) {
        setError("Không thể xác nhận hành trình mới. Vui lòng thử lại.");
        return false;
      }
      if (!f4Run) return false;
      const completed = completeF4Confirmation(f4Run, replacement.plan_id);
      setF4Run(completed.run);
      setConfirmedReplacementPlanId(completed.confirmedPlanId);
      setFailedEvents([]);
      submissionGuard.current.reset();
      const activatedPlan = { ...replacement, status: "CONFIRMED" } as PlanProposal;
      try {
        const resumed = await activateSimulationPlan(tripId, activatedPlan);
        setState(resumed);
        setRecoveryNotice(
          `Đã kích hoạt PLAN v${activatedPlan.version}. Xe đang chạy theo hành trình mới.`,
        );
      } catch (reason) {
        setState(null);
        setError(
          reason instanceof Error
            ? `Đã xác nhận hành trình mới nhưng chưa thể khởi chạy: ${reason.message}`
            : "Đã xác nhận hành trình mới nhưng chưa thể khởi chạy.",
        );
      }
      window.requestAnimationFrame(() => {
        document.getElementById("tracking-route-map")?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      });
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể xác nhận hành trình mới.");
      return false;
    }
  };

  const rejectReplacementPlan = async (replacement: PlanProposal) => {
    setRejectingPlan(true);
    setError("");
    try {
      const rejected = await onRejectPlan(replacement);
      if (!rejected) {
        setError("Không thể từ chối phương án mới. Vui lòng thử lại.");
        return false;
      }
      if (!f4Run) return false;
      const completed = completeF4Rejection(f4Run, replacement.plan_id);
      setF4Run(completed.run);
      setRejectedReplacementPlanId(completed.rejectedPlanId);
      setSafetyWarning("Bạn đã từ chối phương án mới. Nếu kế hoạch hiện tại không còn bảo đảm SOC dự phòng hoặc trạm sạc khả dụng, hãy dừng xe ở vị trí an toàn và gọi hỗ trợ.");
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể từ chối phương án mới.");
      return false;
    } finally {
      setRejectingPlan(false);
    }
  };

  const refreshTelemetryAndContinue = async () => {
    setRefreshingTelemetry(true);
    setError("");
    try {
      const refreshed = await refreshSimulationTelemetry(tripId);
      setState(refreshed);
      setF4Run(null);
      setLiveTrace([]);
      setFailedEvents([]);
      setRecoveryNotice("Đã cập nhật GPS và SOC. Xe đang tiếp tục theo hành trình hiện tại.");
      submissionGuard.current.reset();
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể cập nhật GPS và SOC.");
      return false;
    } finally {
      setRefreshingTelemetry(false);
    }
  };

  const telemetry = state?.telemetry;
  const activeEvents = state ? activeSnapshotEvents(state) : [];
  const latestEvent = activeEvents[activeEvents.length - 1];
  const activeBatchKey = state?.telemetry && activeEvents.length
    ? canonicalEventBatchKey(
        tripId,
        state.telemetry.snapshot_id ?? `sim-${state.tick_count}`,
        activeEvents.map((event) => event.event_id),
      )
    : "";
  const confirmablePlan = f4Run ? getConfirmableF4Plan(f4Run) : null;
  const needsF2Confirmation = !planConfirmed && isPendingF4Plan(plan, confirmablePlan);

  useEffect(() => {
    if (!state || !activeEvents.length || !planConfirmed) return;
    void submitCanonicalEvents(state, activeEvents);
  }, [activeBatchKey, planConfirmed]);

  return <div className="monitor-stack"><section className="monitor-card dashboard-lower-card">
    <div className="monitor-heading"><div><small>F3 · THEO DÕI TRỰC TIẾP</small><h3>Mô phỏng hành trình</h3></div><span className="provenance-badge">● DỮ LIỆU MÔ PHỎNG</span></div>
    {!state || ["STOPPED", "COMPLETED"].includes(state.status) ? <div className="monitor-start">
      <p>Bộ mô phỏng sẽ theo dõi hành trình đã xác nhận và phát sự kiện khi vượt ngưỡng.</p>
      {needsF2Confirmation && confirmablePlan ? <div className="monitor-f2-confirmation">
        <small>F2 · XÁC NHẬN PHƯƠNG ÁN THAY THẾ</small>
        <strong>PLAN v{confirmablePlan.version} đang chờ bạn xác nhận</strong>
        <p>Phương án đã vượt qua kiểm tra an toàn. Chỉ sau khi xác nhận, F3 mới theo dõi hành trình mới.</p>
        <button
          type="button"
          disabled={confirmingPlan}
          onClick={() => { void confirmReplacementPlan(confirmablePlan); }}
        >{confirmingPlan ? "Đang xác nhận…" : "Xác nhận và chuyển sang hành trình mới"}</button>
        <a href="#f4-decision-audit">Xem toàn bộ giải thích F4 ↓</a>
      </div> : <>
        <label className="monitor-scenario-picker">
          <span>Tình huống muốn kiểm thử</span>
          <select
            value={selectedScenario}
            disabled={busy}
            onChange={(event) => {
              const scenario = event.target.value as SimulationScenarioSelection;
              setSelectedScenario(scenario);
              const config = SCENARIO_VALUE_CONFIG[scenario];
              if (config) setScenarioValue(config.defaultValue);
              if (scenario === "MULTI_EVENT") setCompositeEvents(plan.charging_stops.length
                ? ["ROUTE_DEVIATION", "SOC_UNDERPERFORMANCE", "STATION_UNAVAILABLE"]
                : ["ROUTE_DEVIATION", "SOC_UNDERPERFORMANCE"]);
            }}
          >
            {SCENARIO_OPTIONS.map((option) => <option
              key={option.value}
              value={option.value}
              disabled={
                option.value === "STATION_UNAVAILABLE"
                && !plan.charging_stops.length
              }
            >{option.label}</option>)}
          </select>
          <small>{selectedScenario === "RANDOM"
            ? "Chế độ ngẫu nhiên chỉ phát sự cố với xác suất 50%."
            : selectedScenario === "NORMAL"
              ? "Xe sẽ chạy hết hành trình mà không phát sự cố."
              : `Case ${selectedScenario} sẽ được phát chắc chắn trong phiên này.`}</small>
        </label>
        {selectedScenario === "MULTI_EVENT" ? <fieldset className="monitor-composite-events">
          <legend>Chọn 2 hoặc 3 sự kiện cùng một lần đánh giá</legend>
          {COMPOSITE_EVENT_OPTIONS.map((option) => {
            const checked = compositeEvents.includes(option.value);
            const stationUnavailable = option.value === "STATION_UNAVAILABLE" && !plan.charging_stops.length;
            return <label key={option.value}>
              <input
                type="checkbox"
                checked={checked}
                disabled={busy || stationUnavailable || (checked && compositeEvents.length <= 2)}
                onChange={() => setCompositeEvents((items) => checked
                  ? items.filter((item) => item !== option.value)
                  : [...items, option.value])}
              />
              <span>{option.label}</span>
            </label>;
          })}
          <small>{compositeEvents.length} sự kiện sẽ dùng cùng telemetry snapshot và tạo một kế hoạch tổng hợp.</small>
        </fieldset> : null}
        {SCENARIO_VALUE_CONFIG[selectedScenario] ? <div className="monitor-scenario-value">
          <span>{SCENARIO_VALUE_CONFIG[selectedScenario]?.label}</span>
          <div>
            <div className="monitor-threshold-presets" aria-label="Mốc kiểm thử nhanh">
              {SCENARIO_VALUE_CONFIG[selectedScenario]?.presets.map((value) => <button
                key={value}
                type="button"
                className={scenarioValue === value ? "is-active" : ""}
                disabled={busy}
                onClick={() => setScenarioValue(value)}
              >{SCENARIO_VALUE_CONFIG[selectedScenario]?.step === 0.01
                  ? value.toFixed(2)
                  : SCENARIO_VALUE_CONFIG[selectedScenario]?.step === 0.1
                    ? value.toFixed(1)
                    : value.toFixed(0)}</button>)}
            </div>
            <input
              type="number"
              min={0}
              step={SCENARIO_VALUE_CONFIG[selectedScenario]?.step}
              value={scenarioValue}
              disabled={busy}
              aria-label={SCENARIO_VALUE_CONFIG[selectedScenario]?.label}
              onChange={(event) => setScenarioValue(Number(event.target.value))}
            />
          </div>
        </div> : null}
        <label className="monitor-scenario-picker">
          <span>Seed mô phỏng</span>
          <input
            type="number"
            min={0}
            step={1}
            value={simulationSeed}
            disabled={busy}
            onChange={(event) => setSimulationSeed(Math.max(0, Number(event.target.value) || 0))}
          />
          <small>Dùng lại cùng seed để phát lại đúng chuỗi dữ liệu mô phỏng.</small>
        </label>
        {faultInjectionEnabled ? <label className="monitor-scenario-picker">
          <span>Kết quả F1 mô phỏng</span>
          <select
            value={simulationFault}
            disabled={busy}
            onChange={(event) => setSimulationFault(event.target.value as SimulationFault)}
          >
            <option value="NONE">F1 thật</option>
            <option value="F1_PROVIDER_FAILURE">Provider F1 lỗi</option>
            <option value="F1_PROVEN_INFEASIBLE">F1 chứng minh không khả thi</option>
          </select>
          <small>Chỉ áp dụng cho telemetry mô phỏng khi backend bật capability.</small>
        </label> : null}
        <button type="button" onClick={start} disabled={busy || !planConfirmed}>▶ Bắt đầu hành trình</button>
        {!planConfirmed ? <small>Hãy xác nhận hành trình ở bước F2 trước khi mô phỏng.</small> : null}
      </>}
    </div> : null}
    {state ? <>
      <div className="monitor-metrics">
        <div><small>Trạng thái</small><strong>{state.status}</strong></div>
        <div><small>SOC hiện tại</small><strong>{telemetry ? `${telemetry.soc_percent.toFixed(1)}%` : "—"}</strong></div>
        <div><small>SOC dự kiến</small><strong>{telemetry ? `${telemetry.expected_soc_percent.toFixed(1)}%` : "—"}</strong></div>
        <div><small>{confirmedReplacementPlanId ? "Tiến độ tuyến mới" : "Tiến độ"}</small><strong>{telemetry ? `${telemetry.progress_percent.toFixed(1)}%` : "0%"}</strong></div>
      </div>
      <div className="monitor-progress"><span style={{ width: `${telemetry?.progress_percent ?? 0}%` }} /></div>
      <p className="monitor-source">Case: <strong>{state.selected_scenario}</strong> · Seed: <strong>{state.seed}</strong> · Nguồn: dữ liệu mô phỏng · Tăng tốc: <strong>x{state.speed_multiplier}</strong> · Thời gian dự kiến: <strong>{Math.ceil(state.estimated_duration_seconds / 60)} phút</strong></p>
      <div className="monitor-run-controls" aria-label="Điều khiển mô phỏng">
        {state.status === "RUNNING" ? <button type="button" disabled={busy} onClick={() => { void control("pause"); }}>Tạm dừng</button> : null}
        {state.status === "PAUSED" ? <button type="button" disabled={busy} onClick={() => { void control("resume"); }}>Tiếp tục</button> : null}
        {!['COMPLETED', 'STOPPED'].includes(state.status) ? <button type="button" disabled={busy} onClick={() => { void control("reset"); }}>Đặt lại & chạy lại</button> : null}
      </div>
      {state.events.length ? <section className="monitor-event-list" aria-label="Toàn bộ sự kiện mô phỏng">
        <header><strong>Sự kiện đã phát</strong><span>{state.events.length}</span></header>
        <ol>{state.events.map((event, index) => <li className={`monitor-alert monitor-alert--${event.severity.toLowerCase()}`} key={event.event_id}>
          <span>{index + 1}</span>
          <div><strong>{event.event_type}</strong><p>{event.message}</p></div>
          <small>{event.status}</small>
        </li>)}</ol>
      </section> : null}
      {state.status === "AWAITING_DECISION" ? <div className="monitor-decisions">
        {!state.replan_required && !rejectedReplacementPlanId ? <button type="button" onClick={() => void decide("CONTINUE")} disabled={busy}>Bỏ qua và tiếp tục</button> : null}
        <button type="button" onClick={() => void decide("STOP")} disabled={busy}>Dừng chuyến đi</button>
      </div> : null}
    </> : null}
    {busy && latestEvent ? <section className="f4-live-stream" aria-live="polite">
      <header><span className="f4-live-dot" /><div><small>TRỢ LÝ ĐANG PHÂN TÍCH TRỰC TIẾP</small><strong>{activeEvents.length > 1 ? `Hợp nhất ${activeEvents.length} sự kiện đồng thời` : latestEvent.event_type === "SOC_UNDERPERFORMANCE" ? "Bảo vệ mức pin dự phòng" : "Đánh giá sự kiện hành trình"}</strong></div></header>
      {liveTrace.length ? <ol>{liveTrace.map((item) => <li key={item.sequence}>
        <span>{item.sequence}</span>
        <div><strong className="f4-trace-heading">{traceHeading(item.stage, item.tool)}</strong><p>{item.public_summary}</p></div>
        <em>{labelStatus(item.status)}</em>
      </li>)}</ol> : <p>Đang gom telemetry, plan hiện tại, ràng buộc và bằng chứng liên quan…</p>}
    </section> : null}
    {failedEvents.length && state ? <button type="button" onClick={() => void submitCanonicalEvents(state, failedEvents)}>Thử phân tích lại</button> : null}
    {recoveryNotice ? <p className="monitor-recovery-notice" role="status">✓ {recoveryNotice}</p> : null}
    {safetyWarning ? <p className="monitor-safety-warning" role="alert">{safetyWarning}</p> : null}
    {error ? <p className="field-error">{error}</p> : null}
  </section>{f4Run ? <ReplanningSupervisorPanel
    run={f4Run}
    confirming={confirmingPlan}
    confirmedPlanId={confirmedReplacementPlanId}
    rejectedPlanId={rejectedReplacementPlanId}
    onConfirmPlan={confirmReplacementPlan}
    rejecting={rejectingPlan}
    onRejectPlan={rejectReplacementPlan}
    refreshingTelemetry={refreshingTelemetry}
    onRefreshTelemetry={refreshTelemetryAndContinue}
  /> : null}</div>;
}
