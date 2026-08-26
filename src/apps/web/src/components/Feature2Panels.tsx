import { useMemo, useState } from "react";

import type { PlanProposal, PlanVersionSummary } from "../lib/types";

export function StationExplanationPanel({ plan }: { plan: PlanProposal }) {
  const [showRejected, setShowRejected] = useState(false);
  const rejected = Object.entries(plan.explanation?.rejected_station_reasons ?? {});
  return (
    <article className="f2-card">
      <div className="dashboard-card-title"><div><small>Giải thích có căn cứ</small><h2>Lý do đề xuất & đánh giá trạm</h2></div></div>
      <p>{plan.explanation?.summary_text ?? plan.selection_reason}</p>
      <div className="station-explanation-list">
        {plan.charging_stops.map((stop) => (
          <details key={stop.station_id} open>
            <summary>{stop.name}<span>{stop.station_id}</span></summary>
            <p>{plan.explanation?.selected_station_reasons[stop.station_id] ?? "Trạm thuộc chuỗi đã qua Safety Gate."}</p>
          </details>
        ))}
      </div>
      {rejected.length ? (
        <>
          <button className="ghost-button" type="button" onClick={() => setShowRejected((value) => !value)}>
            {showRejected ? "Ẩn trạm bị bỏ qua" : `Xem ${rejected.length} trạm lân cận bị bỏ qua`}
          </button>
          {showRejected ? <div className="rejected-station-list">{rejected.map(([id, reason]) => <div key={id}><strong>{id}</strong><p>{reason}</p></div>)}</div> : null}
        </>
      ) : null}
      <small className="grounding-note">Mỗi số liệu trong lời giải thích được đối chiếu với references route, energy hoặc station từ tool output.</small>
    </article>
  );
}

export function PlanConfirmationBar({
  plan,
  busy,
  onConfirm,
  onReject,
}: {
  plan: PlanProposal;
  busy: boolean;
  onConfirm: () => Promise<void>;
  onReject: (reason: string) => Promise<void>;
}) {
  const [mode, setMode] = useState<"confirm" | "reject" | null>(null);
  const [reason, setReason] = useState("");
  if (plan.status !== "PENDING") return <div className={`plan-decision-result ${plan.status.toLowerCase()}`}>Plan v{plan.version}: {plan.status}</div>;
  return (
    <>
      <section className="plan-confirmation-bar">
        <div><strong>Plan v{plan.version} đang chờ quyết định của bạn</strong><span>Chỉ plan đã xác nhận mới có hiệu lực cho chuyến đi.</span></div>
        <button className="reject-button" type="button" disabled={busy} onClick={() => setMode("reject")}>Từ chối</button>
        <button className="primary-button" type="button" disabled={busy} onClick={() => setMode("confirm")}>Xác nhận kế hoạch</button>
      </section>
      {mode ? <div className="modal-backdrop" role="presentation"><div className="modal-card" role="dialog" aria-modal="true">
        <p className="panel-kicker">Quyết định plan v{plan.version}</p>
        <h3>{mode === "confirm" ? "Xác nhận kế hoạch này?" : "Vì sao bạn từ chối?"}</h3>
        {mode === "confirm" ? <p>{plan.charging_stops.length} điểm sạc · {plan.route.duration_min.toFixed(0)} phút lái · SOC đích {plan.final_arrival_soc_percent.toFixed(1)}% · reserve {plan.assumptions.reserve_soc_percent}%.</p> : <textarea value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Ví dụ: Đường vòng quá xa" maxLength={2000} />}
        <div className="modal-actions"><button className="ghost-button" type="button" disabled={busy} onClick={() => setMode(null)}>Quay lại</button><button className="primary-button" type="button" disabled={busy || (mode === "reject" && !reason.trim())} onClick={async () => { if (mode === "confirm") await onConfirm(); else await onReject(reason.trim()); setMode(null); }}>{busy ? "Đang lưu…" : mode === "confirm" ? "Xác nhận" : "Lưu từ chối"}</button></div>
      </div></div> : null}
    </>
  );
}

export function PlanHistoryTimeline({
  history,
  plans,
  onOpen,
}: {
  history: PlanVersionSummary[];
  plans: PlanProposal[];
  onOpen: (plan: PlanProposal) => void;
}) {
  const [compare, setCompare] = useState(false);
  const diff = useMemo(() => plans.length >= 2 ? buildDiff(plans[plans.length - 2], plans[plans.length - 1]) : null, [plans]);
  if (!history.length) return null;
  return <section className="plan-history-section"><div className="history-heading"><div><small>PlanVersion bất biến</small><h2>Lịch sử kế hoạch</h2></div>{diff ? <button className="ghost-button" type="button" onClick={() => setCompare(true)}>So sánh 2 phiên bản mới nhất</button> : null}</div>
    <div className="plan-timeline">{history.map((item) => { const plan = plans.find((candidate) => candidate.plan_id === item.id); return <button type="button" key={item.id} onClick={() => plan && onOpen(plan)}><span className="timeline-dot"/><strong>v{item.version}</strong><em>{item.status}</em><small>{new Date(item.created_at).toLocaleString("vi-VN")}</small><p>{item.total_distance_km.toFixed(1)} km · {item.stop_count} trạm · {item.risk_level}</p></button>; })}</div>
    {compare && diff ? <div className="modal-backdrop" role="presentation"><div className="modal-card plan-diff-modal" role="dialog" aria-modal="true"><p className="panel-kicker">Plan Diff</p><h3>v{diff.from.version} → v{diff.to.version}</h3><div className="diff-grid"><div><span>Quãng đường</span><strong>{formatDelta(diff.distance)} km</strong></div><div><span>Thời gian</span><strong>{formatDelta(diff.duration)} phút</strong></div><div><span>SOC đích</span><strong>{formatDelta(diff.soc)}%</strong></div><div><span>Trạm thêm</span><strong>{diff.added.join(", ") || "Không"}</strong></div><div><span>Trạm bỏ</span><strong>{diff.removed.join(", ") || "Không"}</strong></div></div><button className="ghost-button" type="button" onClick={() => setCompare(false)}>Đóng</button></div></div> : null}
  </section>;
}

function buildDiff(from: PlanProposal, to: PlanProposal) {
  const oldIds = new Set(from.charging_stops.map((stop) => stop.station_id));
  const newIds = new Set(to.charging_stops.map((stop) => stop.station_id));
  return { from, to, distance: to.route.distance_km - from.route.distance_km, duration: to.route.duration_min - from.route.duration_min, soc: to.final_arrival_soc_percent - from.final_arrival_soc_percent, added: [...newIds].filter((id) => !oldIds.has(id)), removed: [...oldIds].filter((id) => !newIds.has(id)) };
}

function formatDelta(value: number): string { return `${value >= 0 ? "+" : ""}${value.toFixed(1)}`; }
