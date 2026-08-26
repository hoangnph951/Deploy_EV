import type { AssumptionSnapshot } from "../lib/types";

type AssumptionPanelProps = {
  assumptions: AssumptionSnapshot | null;
  loading?: boolean;
  error?: string;
};

function formatTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : new Intl.DateTimeFormat("vi-VN", { dateStyle: "short", timeStyle: "short" }).format(parsed);
}

export function AssumptionPanel({ assumptions, loading = false, error = "" }: AssumptionPanelProps) {
  return (
    <details className="assumption-panel" open>
      <summary className="assumption-summary">
        <span>
          <small>Cơ sở tính toán an toàn</small>
          <strong>Giả định đang áp dụng</strong>
        </span>
        <span className="pilot-badge">Pilot Assumption</span>
      </summary>

      {loading ? <p className="assumption-state">Đang tải cấu hình…</p> : null}
      {error ? <p className="assumption-state error">{error}</p> : null}
      {assumptions ? (
        <div className="assumption-body">
          <div className="assumption-grid">
            <div><span>SOC dự phòng tối thiểu</span><strong>{assumptions.reserve_soc_percent}%</strong></div>
            <div><span>Nhiệt độ baseline (không live)</span><strong>{assumptions.ambient_temperature_c}°C</strong></div>
            <div><span>Tải trọng pilot (không từ xe)</span><strong>{assumptions.vehicle_payload_kg} kg</strong></div>
            <div><span>Phiên bản profile nội bộ</span><strong>{assumptions.vehicle_profile_version}</strong></div>
          </div>
          <p className="pilot-warning">
            Đây là giả định thiết kế pilot; người lái vẫn cần theo dõi điều kiện thực tế.
          </p>
          <div className="assumption-meta">
            <span>Policy: {assumptions.policy_version}</span>
            <span>Nguồn: {assumptions.source} (cấu hình pilot)</span>
            <span>Snapshot: {formatTime(assumptions.created_at)}</span>
          </div>
        </div>
      ) : null}
    </details>
  );
}
