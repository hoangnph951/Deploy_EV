import { useEffect, useState } from "react";
import { decideSimulation, startSimulation, tickSimulation } from "../lib/api";
import type { PlanProposal, SimulationState } from "../lib/types";

type Props = { tripId: string; plan: PlanProposal; onRequestReplan: () => Promise<void>; onStateChange?: (state: SimulationState) => void };

export function TripMonitoringDashboard({ tripId, plan, onRequestReplan, onStateChange }: Props) {
  const [state, setState] = useState<SimulationState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => { if (state) onStateChange?.(state); }, [onStateChange, state]);

  useEffect(() => {
    if (state?.status !== "RUNNING") return;
    const timer = window.setInterval(() => {
      tickSimulation(tripId).then(setState).catch((reason) => setError(reason instanceof Error ? reason.message : "Mất kết nối simulator"));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [state?.status, tripId]);

  const start = async () => {
    setBusy(true); setError("");
    try { setState(await startSimulation(tripId, plan)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Không thể bắt đầu mô phỏng"); }
    finally { setBusy(false); }
  };
  const decide = async (decision: "REQUEST_REPLAN" | "CONTINUE" | "STOP") => {
    setBusy(true);
    try {
      setState(await decideSimulation(tripId, decision));
      if (decision === "REQUEST_REPLAN") await onRequestReplan();
    } finally { setBusy(false); }
  };
  const telemetry = state?.telemetry;
  const latestEvent = state?.events[state.events.length - 1];

  return <section className="monitor-card dashboard-lower-card">
    <div className="monitor-heading"><div><small>F3 · THEO DÕI LIVE</small><h3>Mô phỏng hành trình</h3></div><span className="provenance-badge">● SIMULATED</span></div>
    {!state || ["STOPPED", "COMPLETED"].includes(state.status) ? <div className="monitor-start">
      <p>Mô phỏng sẽ chọn ngẫu nhiên trạng thái hành trình theo xác suất cấu hình sẵn.</p>
      <button type="button" onClick={start} disabled={busy}>▶ Bắt đầu hành trình</button>
    </div> : null}
    {state ? <>
      <div className="monitor-metrics">
        <div><small>Trạng thái</small><strong>{state.status}</strong></div>
        <div><small>SOC hiện tại</small><strong>{telemetry ? `${telemetry.soc_percent.toFixed(1)}%` : "—"}</strong></div>
        <div><small>SOC dự kiến</small><strong>{telemetry ? `${telemetry.expected_soc_percent.toFixed(1)}%` : "—"}</strong></div>
        <div><small>Tiến độ</small><strong>{telemetry ? `${telemetry.progress_percent.toFixed(1)}%` : "0%"}</strong></div>
      </div>
      <div className="monitor-progress"><span style={{ width: `${telemetry?.progress_percent ?? 0}%` }} /></div>
      <p className="monitor-source">Nguồn: dữ liệu mô phỏng · Tăng tốc: <strong>x{state.speed_multiplier}</strong> · Thời gian dự kiến: <strong>{Math.ceil(state.estimated_duration_seconds / 60)} phút</strong> · Agent calls: <strong>{state.agent_invocation_count}</strong></p>
      {latestEvent ? <div className={`monitor-alert monitor-alert--${latestEvent.severity.toLowerCase()}`}><strong>{latestEvent.event_type}</strong><p>{latestEvent.message}</p></div> : null}
      {state.status === "AWAITING_DECISION" ? <div className="monitor-decisions">
        {state.replan_required ? <button type="button" onClick={() => void decide("REQUEST_REPLAN")} disabled={busy}>Lập proposal mới</button> : null}
        <button type="button" onClick={() => void decide("CONTINUE")} disabled={busy}>Bỏ qua & tiếp tục</button>
        <button type="button" onClick={() => void decide("STOP")} disabled={busy}>Dừng chuyến đi</button>
      </div> : null}
    </> : null}
    {error ? <p className="field-error">{error}</p> : null}
  </section>;
}
