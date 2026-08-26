import type { ChargingStopProposal } from "../lib/types";

type Props = {
  stops: ChargingStopProposal[];
  isFeasible: boolean;
};

function formatTimestamp(value: string | null): string {
  if (!value) return "không có timestamp từ nguồn";
  return new Date(value).toLocaleString("vi-VN");
}

export function ChargingStopList({ stops, isFeasible }: Props) {
  if (stops.length === 0) {
    return isFeasible ? (
      <div className="charging-empty">
        <strong>Không cần sạc giữa chặng.</strong> SOC dự kiến vẫn trên ngưỡng dự phòng.
      </div>
    ) : (
      <div className="message-banner error">
        <strong>Không có điểm sạc đã xác minh để tạo phương án an toàn.</strong> Hệ thống không sinh trạm giả.
      </div>
    );
  }

  return (
    <article className="charging-stops-container">
      <h3 className="section-subtitle">Điểm dừng sạc VinFast được đề xuất ({stops.length})</h3>
      <div className="stops-grid">
        {stops.map((stop, index) => (
          <section key={stop.station_id} className="stop-card">
            <div className="stop-card-header">
              <span className="stop-number">{index + 1}</span>
              <div>
                <strong className="stop-name">{stop.name}</strong>
                <div className="stop-address">{stop.address}</div>
              </div>
              <span className={`station-status station-status--${stop.station_status.toLowerCase()}`}>
                Metadata {stop.station_status}
              </span>
            </div>
            <div className="stop-metrics">
              <div className="metric-box"><span className="metric-label">SOC đến/rời</span><strong>{stop.arrival_soc_percent.toFixed(1)}% → {stop.departure_soc_percent.toFixed(1)}%</strong></div>
              <div className="metric-box"><span className="metric-label">Sạc dự kiến</span><strong>{stop.charge_duration_min.toFixed(0)} phút · {stop.energy_added_kwh.toFixed(1)} kWh</strong></div>
              <div className="metric-box"><span className="metric-label">Cổng tương thích đã xác minh</span><strong>{stop.port_count} cổng · {stop.max_power_kw} kW</strong></div>
              <div className="metric-box"><span className="metric-label">Connector</span><strong>{stop.connector_type}</strong><small>{stop.connector_standard}</small></div>
              <div className="metric-box"><span className="metric-label">Đường vòng</span><strong>{stop.detour_distance_km.toFixed(1)} km · {stop.detour_duration_min.toFixed(0)} phút</strong></div>
              <div className="metric-box"><span className="metric-label">Tiếp cận</span><strong>{stop.access_type}{stop.opening_24_7 ? " · 24/7" : ""}</strong><small>{stop.parking_fee ? "Có thể mất phí gửi xe" : "Chưa ghi nhận phí gửi xe"}</small></div>
            </div>
            <footer className="station-provenance">
              Nguồn {stop.provenance?.source ?? "VINFAST_OFFICIAL"} · generation {stop.provenance?.version ?? "không rõ"}
              {" · "}source_updated_at {formatTimestamp(stop.station_updated_at ?? stop.provenance?.source_updated_at ?? null)}
              {" · "}truy xuất {formatTimestamp(stop.provenance?.retrieved_at ?? null)} · {stop.freshness}
              <br />Trạng thái trên là metadata cấp trạm, không phải trạng thái trống/bận/hỏng của từng cổng theo thời gian thực.
            </footer>
          </section>
        ))}
      </div>
    </article>
  );
}
