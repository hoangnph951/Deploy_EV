import type { AssumptionSnapshot, PlanProposal } from "../lib/types";

const RISK_LABEL = {
  LOW_RISK: "Rủi ro thấp",
  MEDIUM_RISK: "Rủi ro trung bình",
  HIGH_RISK: "Rủi ro cao",
  INFEASIBLE: "Không khả thi",
} as const;

function formatDuration(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const remainder = Math.round(minutes % 60);
  return hours ? `${hours} giờ ${remainder} phút` : `${remainder} phút`;
}

export function VehicleSpecs({ assumptions }: { assumptions: AssumptionSnapshot | null }) {
  const profile = assumptions?.vehicle_profile;

  return (
    <details className="vehicle-specs" open>
      <summary>
        <span>
          <small>Xe đang chọn</small>
          <strong>{profile?.name ?? "VinFast VF 6 Plus"}</strong>
        </span>
        <span className="chevron" aria-hidden="true">⌄</span>
      </summary>
      {profile ? (
        <div className="vehicle-spec-body">
          <div className="vehicle-spec-grid">
            <div><span>Pin / khả dụng</span><strong>{profile.battery_capacity_kwh.toLocaleString("vi-VN")} / {profile.usable_capacity_kwh.toLocaleString("vi-VN")} kWh</strong></div>
            <div><span>Range tham chiếu</span><strong>{profile.reference_range_km ?? "—"} km {profile.reference_range_standard}</strong></div>
            <div><span>Động cơ</span><strong>{profile.motor_power_kw ?? "—"} kW</strong></div>
            <div><span>Mô-men xoắn</span><strong>{profile.max_torque_nm ?? "—"} Nm</strong></div>
            <div><span>Chuẩn sạc</span><strong>{profile.connector_type}</strong></div>
            <div><span>Giới hạn sạc mô phỏng</span><strong>{profile.max_charging_power_kw} kW</strong></div>
            <div><span>Sạc nhanh 10–70%</span><strong>~{profile.fast_charge_10_70_min ?? "—"} phút</strong></div>
            <div><span>Tiêu hao baseline</span><strong>{profile.baseline_wh_per_km} Wh/km</strong></div>
            <div><span>Dẫn động</span><strong>{profile.drive_type ?? "—"}</strong></div>
            <div><span>Số chỗ</span><strong>{profile.seats ?? "—"} chỗ</strong></div>
            <div><span>Khối lượng dùng trong model</span><strong>{profile.curb_weight_kg?.toLocaleString("vi-VN") ?? "—"} kg</strong></div>
            <div><span>La-zăng</span><strong>{profile.wheel_size_inch ?? "—"} inch</strong></div>
            <div className="vehicle-spec-wide"><span>Dài × Rộng × Cao</span><strong>{profile.dimensions_mm ?? "—"} mm</strong></div>
            <div><span>Chiều dài cơ sở</span><strong>{profile.wheelbase_mm?.toLocaleString("vi-VN") ?? "—"} mm</strong></div>
            <div><span>Khoảng sáng gầm</span><strong>{profile.ground_clearance_mm ?? "—"} mm</strong></div>
          </div>
          <div className="vehicle-spec-note">
            <span>Profile {profile.version}</span>
            {profile.brochure_range_km ? (
              <span>Brochure hiện hành: {profile.brochure_range_km} km {profile.brochure_range_standard}</span>
            ) : null}
            {profile.official_source_url ? (
              <a href={profile.official_source_url} target="_blank" rel="noreferrer">Nguồn VinFast ↗</a>
            ) : null}
            <span>Baseline, khối lượng và giới hạn sạc là tham số model; các mục còn lại theo nguồn VinFast.</span>
          </div>
        </div>
      ) : (
        <p className="panel-empty">Profile chưa có trong response. Hãy khởi động lại backend để nạp contract mới.</p>
      )}
    </details>
  );
}

export function ProposalSummary({
  plan,
  alternatives,
  onSelectPlan,
  reserveSoc,
  loading,
  planningMessage,
  onChooseJourney,
  confirming,
}: {
  plan: PlanProposal | null;
  alternatives: PlanProposal[];
  onSelectPlan: (plan: PlanProposal) => void;
  reserveSoc: number;
  loading: boolean;
  planningMessage: string;
  onChooseJourney: (plan: PlanProposal) => void;
  confirming?: boolean;
}) {
  return (
    <aside className="proposal-card">
      <div className="dashboard-card-title">
        <div>
          <small>Kết quả tính toán</small>
          <h2>Kế hoạch đề xuất</h2>
        </div>
        {plan ? <span className={`risk-chip risk-chip--${plan.risk_assessment.level.toLowerCase()}`}>{RISK_LABEL[plan.risk_assessment.level]}</span> : null}
      </div>

      {loading ? (
        <div className="agent-progress" aria-live="polite">
          <span className="agent-progress-icon" aria-hidden="true">·</span>
          <strong>{planningMessage || "Agent đang lập kế hoạch…"}</strong>
        </div>
      ) : null}
      {!loading && !plan ? (
        <div className="proposal-empty">
          <span className="proposal-empty-icon">⌁</span>
          <strong>Chưa có kế hoạch</strong>
          <p>Chọn điểm đi, điểm đến và SOC để xem phương án.</p>
        </div>
      ) : null}

      {plan ? (
        <>
          {alternatives.length > 1 ? (
            <div className="alternative-tabs" aria-label="Các phương án an toàn">
              {alternatives.map((alternative) => (
                <button
                  type="button"
                  key={alternative.plan_id}
                  className={alternative.plan_id === plan.plan_id ? "active" : ""}
                  onClick={() => onSelectPlan(alternative)}
                >
                  PA {alternative.alternative_rank} · {alternative.strategy === "BALANCED" ? "Cân bằng" : alternative.strategy === "FASTEST" ? "Nhanh nhất" : "An toàn nhất"}
                </button>
              ))}
            </div>
          ) : null}
          {plan.route.detour_distance_km > 0 ? (
            <div className={`route-detour-note ${plan.route.includes_backtracking ? "backtracking" : ""}`}>
              <strong>{plan.route.includes_backtracking ? "Có quay lại trạm gần điểm xuất phát" : "Có lệch tuyến tới trạm"}</strong>
              <span>Thêm {plan.route.detour_distance_km.toFixed(1)} km · khoảng {plan.route.detour_duration_min.toFixed(0)} phút so với tuyến thẳng.</span>
            </div>
          ) : null}
          <div className="proposal-primary-metrics">
            <div><span>Quãng đường</span><strong>{plan.route.distance_km.toLocaleString("vi-VN", { maximumFractionDigits: 1 })}<small> km</small></strong></div>
            <div><span>Thời gian</span><strong>{formatDuration(plan.route.duration_min)}</strong></div>
          </div>
          <div className="proposal-secondary-metrics">
            <div><span>SOC đến đích</span><strong>{plan.final_arrival_soc_percent.toFixed(1)}%</strong></div>
            <div><span>Dự phòng</span><strong>{reserveSoc}%</strong></div>
            <div><span>Tiêu hao</span><strong>{plan.effective_consumption_wh_per_km.toFixed(0)} Wh/km</strong></div>
          </div>

          <div className="proposal-stops">
            {plan.charging_stops.length === 0 ? (
              <div className="no-charge-needed"><span>✓</span><div><strong>Không cần dừng sạc</strong><small>SOC đến đích vẫn trên mức dự phòng.</small></div></div>
            ) : plan.charging_stops.map((stop, index) => (
              <article className="proposal-stop" key={stop.station_id}>
                <header><span className="charge-icon">ϟ</span><div><small>Điểm sạc {index + 1}</small><strong>{stop.name}</strong></div></header>
                <div className="stop-soc-flow">
                  <div><span>Đến trạm</span><strong>{stop.arrival_soc_percent.toFixed(1)}%</strong></div>
                  <span aria-hidden="true">→</span>
                  <div><span>Rời trạm</span><strong>{stop.departure_soc_percent.toFixed(1)}%</strong></div>
                </div>
                <div className="stop-compact-meta">
                  <span>{stop.connector_type}</span><span>{stop.max_power_kw} kW</span><span>{stop.port_count} cổng</span><span>{stop.charge_duration_min.toFixed(0)} phút</span>
                </div>
                <small className="station-live-note">Trạng thái hoạt động là metadata cấp trạm, không phải số cổng trống realtime.</small>
              </article>
            ))}
          </div>

          <div className="plan-identity">PLAN v{plan.version} · {plan.status} · {plan.route.provider}</div>
          <p className="selection-reason">{plan.selection_reason} · Giải thích: {plan.explanation_source === "OPENAI" ? "OpenAI trên dữ liệu đã kiểm chứng" : "quy tắc deterministic"}</p>
          {plan.risk_assessment.is_feasible ? <button className="choose-journey-button" type="button" disabled={confirming || plan.status === "CONFIRMED"} onClick={() => onChooseJourney(plan)}>{plan.status === "CONFIRMED" ? "✓ Hành trình đã xác nhận" : confirming ? "Đang xác nhận…" : "✓ Xác nhận hành trình"}</button> : null}
        </>
      ) : null}
    </aside>
  );
}

export function DataTrustPanel({ plan }: { plan: PlanProposal }) {
  const labels: Record<string, string> = {
    ROUTE: "Tuyến đường",
    STATION_DATASET: "Bộ dữ liệu trạm",
    STATION_DETAIL: "Cấu hình trạm / cổng",
    WEATHER: "Thời tiết",
    ELEVATION: "Độ cao",
    VEHICLE_PROFILE: "Profile xe",
    POLICY_CONFIG: "Chính sách an toàn",
    PLANNER_ALGORITHM: "Thuật toán planner",
    ENERGY_MODEL: "Mô hình năng lượng",
  };
  const age = (timestamp: string) => Math.max(0, Date.now() - new Date(timestamp).getTime());
  const ageLabel = (timestamp: string) => {
    const hours = age(timestamp) / 3_600_000;
    if (hours < 1) return `${Math.max(0, Math.round(hours * 60))} phút`;
    if (hours < 48) return `${hours.toFixed(1)} giờ`;
    return `${Math.floor(hours / 24)} ngày`;
  };
  const trust = (source: PlanProposal["provenance"][number]) => {
    if (source.source === "OPENAI_WEB_SEARCH") return "UNVERIFIED";
    if (
      (source.kind === "STATION_DATASET" || source.kind === "STATION_DETAIL")
      && age(source.source_updated_at ?? source.retrieved_at)
        > plan.assumptions.stale_station_hours_threshold * 3_600_000
    ) return "STALE";
    return "FRESH";
  };
  return (
    <article className="trust-card dashboard-lower-card">
      <div className="dashboard-card-title"><div><small>Minh bạch</small><h2>Nguồn dữ liệu</h2></div></div>
      <div className="trust-list">
        {plan.provenance.map((source, index) => (
          <div key={`${source.kind}-${source.source}-${index}`}>
            <span className={`source-dot source-dot--${trust(source).toLowerCase()}`} />
            <strong>{labels[source.kind ?? ""] ?? source.kind ?? "Nguồn dữ liệu"}</strong>
            <span>
              {/^https?:\/\//.test(source.source_url) ? (
                <a href={source.source_url} target="_blank" rel="noreferrer">{source.source}</a>
              ) : source.source}
              {source.generation || source.version ? ` · ${source.generation ?? source.version}` : ""}
            </span>
            <small>{trust(source)} · {ageLabel(source.source_updated_at ?? source.retrieved_at)}</small>
          </div>
        ))}
      </div>
      <div className="live-conditions">
        <span>{plan.environment?.temperature_c.toFixed(1) ?? "—"}°C</span>
        <span>{plan.environment?.wind_speed_kmh.toFixed(1) ?? "—"} km/h gió</span>
        <span>+{plan.environment?.elevation_gain_m.toFixed(0) ?? "—"} m</span>
      </div>
      <p className="data-caveat">Không có trạng thái trống/bận/hỏng theo từng cổng sạc thời gian thực.</p>
    </article>
  );
}

export function PlanHistoryPanel({ plans, onSelectPlan }: {
  plans: PlanProposal[];
  onSelectPlan: (plan: PlanProposal) => void;
}) {
  const primaryPlans = plans
    .filter((plan) => plan.alternative_rank === 1)
    .sort((left, right) => right.version - left.version);
  return (
    <article className="history-card dashboard-lower-card">
      <div className="dashboard-card-title"><div><small>Đã lưu</small><h2>Lịch sử kế hoạch</h2></div></div>
      {primaryPlans.length ? (
        <div className="plan-history-list">
          {primaryPlans.map((plan) => (
            <button type="button" key={plan.plan_id} onClick={() => onSelectPlan(plan)}>
              <strong>PLAN v{plan.version}</strong>
              <span>{plan.status} · {plan.strategy}</span>
              <small>{new Date(plan.created_at).toLocaleString("vi-VN")}</small>
            </button>
          ))}
        </div>
      ) : <p className="panel-empty">Chưa có kế hoạch đã lưu.</p>}
    </article>
  );
}

export function WhyThisPlan({ plan }: { plan: PlanProposal }) {
  const reserve = plan.assumptions.reserve_soc_percent;
  const explanations = [
    `SOC đến đích ${plan.final_arrival_soc_percent.toFixed(1)}% ${plan.final_arrival_soc_percent >= reserve ? "đạt" : "không đạt"} mức dự phòng ${reserve}%.`,
    plan.charging_stops.length
      ? `${plan.charging_stops.length} trạm đề xuất tương thích ${plan.charging_stops.map((stop) => stop.connector_type).filter((value, index, all) => all.indexOf(value) === index).join(", ")}.`
      : "Không cần ghé trạm sạc theo mức tiêu hao dự kiến.",
    ...plan.risk_assessment.reasons,
  ];
  return (
    <article className="why-card dashboard-lower-card">
      <div className="dashboard-card-title"><div><small>Giải thích quyết định</small><h2>Vì sao chọn phương án này?</h2></div></div>
      <div className="why-list">
        {explanations.slice(0, 4).map((reason, index) => (
          <div key={`${reason}-${index}`}><span>{plan.risk_assessment.is_feasible ? "✓" : "!"}</span><p>{reason}</p></div>
        ))}
      </div>
      <div className={`risk-score risk-score--${plan.risk_assessment.is_feasible ? "safe" : "danger"}`}>
        <span>Điểm rủi ro</span><strong>{plan.risk_assessment.risk_score.toFixed(0)}/100</strong>
      </div>
    </article>
  );
}
