import { useEffect, useState } from "react";

import {
  explainReasonCode,
  labelAction,
  labelHypothesis,
  labelObjective,
  labelStatus,
  labelTraceKind,
  publicEvidenceSummary,
  traceHeading,
} from "../lib/replanningPresentation";
import { getConfirmableF4Plan } from "../lib/f4Confirmation";
import type { PlanProposal, ReplanningOutcome } from "../lib/types";

type Props = {
  run: ReplanningOutcome;
  confirming?: boolean;
  confirmedPlanId?: string;
  rejectedPlanId?: string;
  onConfirmPlan?: (plan: PlanProposal) => Promise<boolean>;
  rejecting?: boolean;
  onRejectPlan?: (plan: PlanProposal) => Promise<boolean>;
  refreshingTelemetry?: boolean;
  onRefreshTelemetry?: () => Promise<boolean>;
};

export function ReplanningSupervisorPanel({
  run, confirming = false, confirmedPlanId = "", rejectedPlanId = "", onConfirmPlan,
  rejecting = false, onRejectPlan,
  refreshingTelemetry = false, onRefreshTelemetry,
}: Props) {
  const constraints = run.context.unresolved_constraints;
  const confirmablePlan = getConfirmableF4Plan(run);
  const replacementConfirmed = confirmablePlan?.plan_id === confirmedPlanId;
  const replacementRejected = confirmablePlan?.plan_id === rejectedPlanId;
  const candidatePlan = confirmablePlan;
  const evidence = Array.from(new Set([
    ...run.tool_runs.flatMap((tool) => tool.provenance_refs),
    ...run.reflection.evidence_refs,
  ]));
  const evidenceSummary = publicEvidenceSummary(
    evidence,
    constraints.excluded_station_ids,
  );
  const [visibleTraceCount, setVisibleTraceCount] = useState(1);

  useEffect(() => {
    setVisibleTraceCount(1);
    const timer = window.setInterval(() => {
      setVisibleTraceCount((current) => {
        if (current >= run.decision_trace.length) {
          window.clearInterval(timer);
          return current;
        }
        return current + 1;
      });
    }, 480);
    return () => window.clearInterval(timer);
  }, [run.agent_run_id, run.decision_trace.length]);

  const traceComplete = visibleTraceCount >= run.decision_trace.length;

  return <section className="f4-panel" id="f4-decision-audit" aria-live="polite">
    <div className="monitor-heading">
      <div><small>F4 · TRỢ LÝ ĐIỀU CHỈNH HÀNH TRÌNH</small><h3>Nhật ký phân tích trực tiếp</h3></div>
      <span className={`safety-chip safety-chip--${run.status.toLowerCase()}`}>{traceComplete ? labelStatus(run.status) : "Đang hiển thị"}</span>
    </div>

    <div className="f4-section">
      <small>Tình huống được phát hiện</small>
      <strong>{run.epoch.event_ids.length} sự kiện trong lần đánh giá này</strong>
      <p>Ngữ cảnh hành trình phiên bản {run.context.context_version}; phương án nền phiên bản {run.epoch.base_plan_version}.</p>
    </div>

    <div className="f4-section">
      <small>Mục tiêu an toàn</small>
      <strong>{labelObjective(run.assessment.primary_objective)}</strong>
      <p>{run.assessment.public_summary || run.assessment.strategy}</p>
      <p>Mức khẩn cấp: {run.assessment.urgency} · Độ tin cậy đánh giá: {Math.round(run.assessment.confidence * 100)}%</p>
    </div>

    <div className="f4-section">
      <small>Các bước kiểm tra của trợ lý</small>
      <ol className="f4-decision-timeline">
        {run.decision_trace.slice(0, visibleTraceCount).map((item, index) => <li className={`f4-trace-${item.stage.toLowerCase()}`} key={item.sequence}>
          <div><strong className="f4-trace-heading">{traceHeading(item.stage, item.tool)}</strong><span>{index === visibleTraceCount - 1 && !traceComplete ? "Đang xử lý" : labelStatus(item.status)}</span></div>
          <em>{labelTraceKind(item.stage, item.response_source)}</em>
          {item.public_summary ? <small className="f4-public-summary">{item.public_summary}</small> : item.reason_codes.map((code) => <small key={code}>{explainReasonCode(code)}</small>)}
        </li>)}
      </ol>
    </div>

    <div className="f4-section">
      <small>Bằng chứng đã thu thập</small>
      <p>{evidenceSummary.evidenceNotice}</p>
      <p>Dữ liệu xe: <strong>{constraints.telemetry_blocked ? "Đã cũ hoặc thiếu" : "Còn hiệu lực"}</strong></p>
      <p>{evidenceSummary.excludedStationsNotice}</p>
    </div>

    <div className="f4-section">
      <small>Điều còn thiếu hoặc chưa chắc chắn</small>
      {run.reflection.missing_evidence.length
        ? <ul>{run.reflection.missing_evidence.map((item) => <li key={item}>{item}</li>)}</ul>
        : <p>Không còn thiếu bằng chứng bắt buộc ở thời điểm ra quyết định.</p>}
    </div>

    {run.plan_diff ? <div className="f4-section">
      <small>So sánh hành trình hiện tại và phương án mới</small>
      <div className="f4-diff-grid">
        <span>Quãng đường <strong>{run.plan_diff.distance_delta_km >= 0 ? "+" : ""}{run.plan_diff.distance_delta_km} km</strong></span>
        <span>Thời gian <strong>{run.plan_diff.duration_delta_min >= 0 ? "+" : ""}{run.plan_diff.duration_delta_min} phút</strong></span>
        <span>Pin khi đến đích <strong>{run.plan_diff.final_soc_delta_percent >= 0 ? "+" : ""}{run.plan_diff.final_soc_delta_percent}%</strong></span>
        <span>Biên dự phòng <strong>{run.plan_diff.reserve_margin_delta_percent >= 0 ? "+" : ""}{run.plan_diff.reserve_margin_delta_percent}%</strong></span>
      </div>
    </div> : null}

    {candidatePlan ? <div className="f4-section f4-candidate-summary">
      <small>Hành trình thay thế sẽ được áp dụng</small>
      <strong>PLAN v{candidatePlan.version} · {run.candidate?.strategy === "MINIMAL_SUBSTITUTION" ? "Thay trạm tối thiểu" : "Lập lại toàn bộ"}</strong>
      <div className="f4-candidate-metrics">
        <span>{candidatePlan.route.distance_km.toFixed(1)} km</span>
        <span>{candidatePlan.route.duration_min.toFixed(0)} phút</span>
        <span>SOC đích {candidatePlan.final_arrival_soc_percent.toFixed(1)}%</span>
      </div>
      {candidatePlan.charging_stops.length ? <div className="f4-replacement-stations">
        <b>Trạm trên tuyến mới:</b>
        {candidatePlan.charging_stops.map((stop, index) => <p key={stop.station_id}>
          <span>{index + 1}</span><strong>{stop.name}</strong><small>{stop.address} · {stop.max_power_kw} kW</small>
        </p>)}
      </div> : <p className="f4-no-charge-needed">
        Tuyến full replan không cần dừng sạc: F1 đã chứng minh SOC hiện tại đủ tới đích và vẫn giữ mức dự phòng.
      </p>}
      <p className="f4-excluded-stations">{evidenceSummary.excludedStationsNotice}</p>
    </div> : null}

    <div className="f4-section">
      <small>Kết luận an toàn</small>
      <strong>{labelHypothesis(run.reflection.hypothesis_status)}</strong>
      <p>{run.reflection.public_summary}</p>
      <p>{run.candidate ? labelStatus(run.candidate.feasibility_verdict) : "Không tạo phương án mới khi dữ liệu chưa đạt yêu cầu."}</p>
    </div>

    <div className="f4-action">
      <small>Hành động đề xuất</small>
      <strong>{labelAction(run.action.action)}</strong>
      <p>{run.action.public_summary || run.action.user_message}</p>
      {confirmablePlan ? <a className="f4-view-route" href="#tracking-route-map">
        {replacementConfirmed ? "Xem hành trình đang đi trên bản đồ ↑" : "Xem tuyến thay thế trên bản đồ ↑"}
      </a> : null}
      {replacementRejected
        ? <span className="f4-pending-confirmation">Phương án đã bị từ chối · Xe vẫn đang chờ quyết định an toàn</span>
        : run.action.requires_owner_confirmation
          ? <span className="f4-pending-confirmation">Đang chờ bạn xác nhận hoặc từ chối</span>
          : null}
      {run.action.limitations.map((item) => <p className="f4-limitation" key={item}>⚠ {item}</p>)}
      {run.action.action === "REQUEST_NEW_TELEMETRY" && onRefreshTelemetry ? <button
        className="f4-refresh-telemetry-button"
        type="button"
        disabled={refreshingTelemetry}
        onClick={() => { void onRefreshTelemetry(); }}
      >{refreshingTelemetry ? "Đang cập nhật GPS và SOC…" : "⌖ Cập nhật GPS & SOC rồi tiếp tục"}</button> : null}
      {confirmablePlan && onConfirmPlan ? <div className="f4-decision-actions">
        {onRejectPlan ? <button
          className="f4-reject-button"
          type="button"
          disabled={confirming || rejecting || replacementConfirmed || replacementRejected}
          onClick={() => { void onRejectPlan(confirmablePlan); }}
        >{replacementRejected ? "Phương án đã bị từ chối" : rejecting ? "Đang từ chối…" : "Từ chối phương án"}</button> : null}
        <button
          className="f4-confirm-button"
          type="button"
          disabled={confirming || rejecting || replacementConfirmed || replacementRejected}
          onClick={() => { void onConfirmPlan(confirmablePlan); }}
        >{replacementConfirmed
            ? "✓ Hành trình mới đã được xác nhận"
            : confirming
              ? "Đang xác nhận hành trình mới…"
              : "Xác nhận hành trình mới"}</button>
      </div> : null}
    </div>

    <details className="f4-section">
      <summary>Chi tiết kỹ thuật</summary>
      <p>{run.assessment.reason_codes.join(", ") || "Không có mã bổ sung"}</p>
    </details>
  </section>;
}
