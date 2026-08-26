import type { NoFeasiblePlan } from "../lib/types";

type Props = { result: NoFeasiblePlan };

const LABELS = {
  LOW_RISK: "Rủi ro thấp",
  MEDIUM_RISK: "Rủi ro trung bình",
  HIGH_RISK: "Rủi ro cao",
  INFEASIBLE: "Không khả thi",
} as const;

const REASON_LABELS: Record<string, string> = {
  SOC_BELOW_RESERVE_15: "Pin không đủ để giữ mức dự phòng 15%",
  INITIAL_SOC_BELOW_RESERVE: "SOC khởi hành thấp hơn mức dự phòng",
  UNREACHABLE_NEXT_STATION: "Chưa tìm được trạm tiếp theo có thể tiếp cận an toàn",
  NO_COMPATIBLE_CONNECTOR: "Chưa có trạm tương thích với cổng sạc của xe",
  DETOUR_DISTANCE_EXCEEDED: "Trạm tìm được yêu cầu đi vòng quá xa",
  DETOUR_TIME_EXCEEDED: "Trạm tìm được làm thời gian đi vòng vượt giới hạn",
};

export function InfeasibleWarningBanner({ result }: Props) {
  const assessment = result.risk_assessment;
  const variant = assessment.level === "LOW_RISK"
    ? "low"
    : assessment.level === "MEDIUM_RISK"
      ? "medium"
      : "danger";

  return (
    <article className={`risk-banner risk-banner--${variant}`}>
      <div className={`risk-badge risk-badge--${variant}`}>
        {LABELS[assessment.level]} · {assessment.risk_score.toFixed(0)}/100
      </div>
      <p className="risk-summary">
        {assessment.is_feasible
          ? "Kế hoạch vượt qua các kiểm tra SOC dự phòng, connector và trạng thái trạm."
          : "Hệ thống từ chối đề xuất kế hoạch vì không chứng minh được hành trình an toàn."}
      </p>
      {assessment.reasons.length > 0 && (
        <ul className="risk-reasons">
          {assessment.reasons.map((reason, index) => <li key={`${reason}-${index}`}>{reason}</li>)}
        </ul>
      )}
      {!assessment.is_feasible && (
        <div className="risk-actions">
          {result.direct_route_distance_km != null ? (
            <div className="infeasible-diagnostics">
              <div><span>Xe đang tính</span><strong>{result.vehicle_profile_name ?? "Profile hiện tại"}</strong></div>
              <div><span>Pin khả dụng</span><strong>{result.usable_battery_kwh?.toFixed(2) ?? "-"} kWh</strong></div>
              <div><span>Toàn tuyến</span><strong>{result.direct_route_distance_km.toFixed(0)} km</strong></div>
              <div><span>Có thể đi trước ngưỡng 15%</span><strong>khoảng {result.estimated_reachable_distance_km?.toFixed(0) ?? "-"} km</strong></div>
              <div><span>Năng lượng đang dùng được</span><strong>{result.available_energy_before_reserve_kwh?.toFixed(1) ?? "-"} kWh</strong></div>
              <div><span>Năng lượng còn thiếu cho toàn tuyến</span><strong>{result.energy_shortfall_kwh?.toFixed(1) ?? "-"} kWh</strong></div>
              {result.nearest_candidate_station_distance_km != null ? (
                <div><span>Trạm gần nhất được tìm thấy</span><strong>{result.nearest_candidate_station_distance_km.toFixed(1)} km</strong></div>
              ) : null}
            </div>
          ) : null}
          <strong>
            Đã tìm thấy {result.evaluated_station_count} ứng viên trạm tương thích trong cửa sổ tìm kiếm; không phải tất cả đều nằm trong tầm đi an toàn của SOC hiện tại.
          </strong>
          {result.estimated_minimum_charging_stops != null && result.estimated_minimum_charging_stops > 0 ? (
            <span>
              Về năng lượng, hành trình ước tính cần ít nhất {result.estimated_minimum_charging_stops} lần sạc dọc đường.
              Hệ thống hiện chưa xác minh được một chuỗi trạm liên tục đáp ứng ngưỡng 15%.
            </span>
          ) : null}
          {result.minimum_initial_soc_percent != null ? <span>SOC để đi thẳng theo mô hình: khoảng {result.minimum_initial_soc_percent.toFixed(1)}% trở lên.</span> : null}
          {result.suggestions.map((suggestion) => <span key={suggestion}>• {suggestion}</span>)}
          {assessment.reason_codes.length ? (
            <div className="reason-code-list">
              {assessment.reason_codes.map((code) => (
                <span key={code}><strong>{REASON_LABELS[code] ?? code}</strong><small>{code}</small></span>
              ))}
            </div>
          ) : null}
        </div>
      )}
    </article>
  );
}
