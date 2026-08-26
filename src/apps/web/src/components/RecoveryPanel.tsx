import type { PlanningRecoveryResponse, RecoveryOption } from "../lib/types";

type Props = {
  result: PlanningRecoveryResponse;
  onApplyEndpoint: (option: RecoveryOption) => void;
};

export function RecoveryPanel({ result, onApplyEndpoint }: Props) {
  const conditional = result.outcome === "CONDITIONAL";
  return (
    <article className={`risk-banner risk-banner--${conditional ? "medium" : "danger"}`}>
      <div className={`risk-badge risk-badge--${conditional ? "medium" : "danger"}`}>
        {conditional
          ? "Kế hoạch có điều kiện"
          : result.outcome === "SEARCH_EXHAUSTED"
            ? "Chưa duyệt xong đồ thị trạm"
          : result.outcome === "ACTION_REQUIRED" && result.http_status === 429
            ? "Dịch vụ bản đồ đang giới hạn lượt gọi"
            : "Cần người dùng quyết định"}
      </div>
      <p className="risk-summary">{result.summary}</p>
      {result.outcome === "ACTION_REQUIRED" ? (
        <small className="provider-diagnostic">
          {result.provider || "PLANNING"}
          {result.provider_status ? ` · ${result.provider_status}` : ""}
          {result.http_status ? ` · HTTP ${result.http_status}` : ""}
        </small>
      ) : null}
      <div className="risk-actions">
        {result.recovery_options.map((option) => (
          <div key={`${option.code}-${option.title}`}>
            <strong>{option.title}{option.verified ? " · Đã xác minh tuyến" : ""}</strong>
            <span>{option.description}</span>
            {option.source_url ? <a href={option.source_url} target="_blank" rel="noreferrer">Mở nguồn đối chiếu</a> : null}
            {option.action === "CHANGE_ENDPOINT" && option.lat != null && option.lng != null ? (
              <button type="button" onClick={() => onApplyEndpoint(option)}>Dùng điểm tiếp cận này</button>
            ) : null}
          </div>
        ))}
      </div>
    </article>
  );
}
