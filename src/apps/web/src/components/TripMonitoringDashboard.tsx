import { useEffect, useRef, useState } from "react";

import {
  activateSimulationPlan,
  decideSimulation,
  refreshSimulationTelemetry,
  startSimulation,
  tickSimulation,
} from "../lib/api";
import { canonicalEventKey, ReplanningSubmissionGuard } from "../lib/replanningSubmission";
import { completeF4Confirmation, getConfirmableF4Plan, isPendingF4Plan } from "../lib/f4Confirmation";
import { labelStage, labelStatus, labelTool } from "../lib/replanningPresentation";
import type {
  PlanProposal,
  ReplanningOutcome,
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
  { value: "RANDOM", label: "Ngẫu nhiên · 50% có sự cố" },
];
type Props = {
  tripId: string;
  plan: PlanProposal;
  planConfirmed: boolean;
  onCanonicalEvent: (
    state: SimulationState,
    event: CanonicalEvent,
    onTrace: (trace: ReplanningOutcome["decision_trace"][number]) => void,
  ) => Promise<ReplanningOutcome | null>;
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
  const [failedEvent, setFailedEvent] = useState<CanonicalEvent | null>(null);
  const [rejectingPlan, setRejectingPlan] = useState(false);
  const [liveTrace, setLiveTrace] = useState<ReplanningOutcome["decision_trace"]>([]);
  const [recoveryNotice, setRecoveryNotice] = useState("");
  const [refreshingTelemetry, setRefreshingTelemetry] = useState(false);
  const [selectedScenario, setSelectedScenario] = useState<SimulationScenarioSelection>("NORMAL");
  const submissionGuard = useRef(new ReplanningSubmissionGuard());

  useEffect(() => {
    submissionGuard.current.reset();
    setF4Run(null);
    setConfirmedReplacementPlanId("");
    setFailedEvent(null);
    setSelectedScenario("NORMAL");
  }, [tripId]);

  useEffect(() => {
    if (!plan.charging_stops.length && selectedScenario === "STATION_UNAVAILABLE") {
      setSelectedScenario("NORMAL");
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
    setBusy(true); setError(""); setRecoveryNotice("");
    try { setState(await startSimulation(tripId, plan, selectedScenario)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Không thể bắt đầu mô phỏng."); }
    finally { setBusy(false); }
  };

  const decide = async (decision: "CONTINUE" | "STOP") => {
    setBusy(true);
    try { setState(await decideSimulation(tripId, decision)); }
    finally { setBusy(false); }
  };

  const submitCanonicalEvent = async (current: SimulationState, event: CanonicalEvent) => {
    const key = canonicalEventKey(tripId, event.event_id);
    if (!submissionGuard.current.begin(key)) return;
    setBusy(true); setError(""); setRecoveryNotice(""); setFailedEvent(null);
    setLiveTrace([]);
    try {
      setF4Run(await onCanonicalEvent(current, event, (trace) => {
        setLiveTrace((items) => (
          items.some((item) => item.sequence === trace.sequence) ? items : [...items, trace]
        ));
      }));
      setConfirmedReplacementPlanId("");
      submissionGuard.current.complete(key);
    } catch (reason) {
      submissionGuard.current.fail(key);
      setFailedEvent(event);
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
      setFailedEvent(null);
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
      setState(null);
      setF4Run(null);
      setFailedEvent(null);
      submissionGuard.current.reset();
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
      setFailedEvent(null);
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
  const latestEvent = state
    ? [...state.events].reverse().find((event) => event.status !== "RESOLVED")
    : undefined;
  const confirmablePlan = f4Run ? getConfirmableF4Plan(f4Run) : null;
  const needsF2Confirmation = !planConfirmed && isPendingF4Plan(plan, confirmablePlan);

  useEffect(() => {
    if (!state || !latestEvent || !planConfirmed) return;
    void submitCanonicalEvent(state, latestEvent);
  }, [latestEvent?.event_id, planConfirmed, state?.telemetry?.snapshot_id]);

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
            onChange={(event) => setSelectedScenario(event.target.value as SimulationScenarioSelection)}
          >
            {SCENARIO_OPTIONS.map((option) => <option
              key={option.value}
              value={option.value}
              disabled={option.value === "STATION_UNAVAILABLE" && !plan.charging_stops.length}
            >{option.label}</option>)}
          </select>
          <small>{selectedScenario === "RANDOM"
            ? "Chế độ ngẫu nhiên chỉ phát sự cố với xác suất 50%."
            : selectedScenario === "NORMAL"
              ? "Xe sẽ chạy hết hành trình mà không phát sự cố."
              : `Case ${selectedScenario} sẽ được phát chắc chắn trong phiên này.`}</small>
        </label>
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
      <p className="monitor-source">Case: <strong>{state.selected_scenario}</strong> · Nguồn: dữ liệu mô phỏng · Tăng tốc: <strong>x{state.speed_multiplier}</strong> · Thời gian dự kiến: <strong>{Math.ceil(state.estimated_duration_seconds / 60)} phút</strong></p>
      {latestEvent ? <div className={`monitor-alert monitor-alert--${latestEvent.severity.toLowerCase()}`}><strong>{latestEvent.event_type}</strong><p>{latestEvent.message}</p></div> : null}
      {state.status === "AWAITING_DECISION" ? <div className="monitor-decisions">
        <button type="button" onClick={() => void decide("CONTINUE")} disabled={busy}>Bỏ qua và tiếp tục</button>
        <button type="button" onClick={() => void decide("STOP")} disabled={busy}>Dừng chuyến đi</button>
      </div> : null}
    </> : null}
    {busy && latestEvent ? <section className="f4-live-stream" aria-live="polite">
      <header><span className="f4-live-dot" /><div><small>TRỢ LÝ ĐANG PHÂN TÍCH TRỰC TIẾP</small><strong>{latestEvent.event_type === "SOC_UNDERPERFORMANCE" ? "Bảo vệ mức pin dự phòng" : "Đánh giá sự kiện hành trình"}</strong></div></header>
      {liveTrace.length ? <ol>{liveTrace.map((item) => <li key={item.sequence}>
        <span>{item.sequence}</span>
        <div><strong>{labelStage(item.stage)}</strong>{item.tool ? <small>{labelTool(item.tool)}</small> : null}<p>{item.public_summary}</p></div>
        <em>{labelStatus(item.status)}</em>
      </li>)}</ol> : <p>Đang gom telemetry, plan hiện tại, ràng buộc và bằng chứng liên quan…</p>}
    </section> : null}
    {failedEvent && state ? <button type="button" onClick={() => void submitCanonicalEvent(state, failedEvent)}>Thử phân tích lại</button> : null}
    {recoveryNotice ? <p className="monitor-recovery-notice" role="status">✓ {recoveryNotice}</p> : null}
    {error ? <p className="field-error">{error}</p> : null}
  </section>{f4Run ? <ReplanningSupervisorPanel
    run={f4Run}
    confirming={confirmingPlan}
    confirmedPlanId={confirmedReplacementPlanId}
    onConfirmPlan={confirmReplacementPlan}
    rejecting={rejectingPlan}
    onRejectPlan={rejectReplacementPlan}
    refreshingTelemetry={refreshingTelemetry}
    onRefreshTelemetry={refreshTelemetryAndContinue}
  /> : null}</div>;
}
