import type { PlanProposal } from "../lib/types";

export function PlanDataPanel({ plan }: { plan: PlanProposal }) {
  const environment = plan.environment;
  if (!environment) return null;

  return (
    <>
      {environment.is_degraded ? (
        <div className="message-banner warning" role="status">
          {environment.warning ?? "Đang dùng giả định môi trường có biên dự phòng."}
          {environment.consumption_margin_percent > 0
            ? ` Biên tiêu hao +${environment.consumption_margin_percent.toFixed(0)}%.`
            : ""}
        </div>
      ) : null}
      <article className="plan-data-panel">
        <div>
          <span>{environment.status === "LIVE" ? "Nhiệt độ live" : "Nhiệt độ giả định"}</span>
          <strong>{environment.temperature_c.toFixed(1)}°C</strong>
        </div>
        <div>
          <span>Gió / mưa</span>
          <strong>
            {environment.wind_speed_kmh.toFixed(1)} km/h · {environment.precipitation_mm.toFixed(1)} mm
          </strong>
        </div>
        <div>
          <span>Độ cao tuyến</span>
          <strong>
            +{environment.elevation_gain_m.toFixed(0)} m / −{environment.elevation_loss_m.toFixed(0)} m
          </strong>
        </div>
        <div>
          <span>Tiêu hao dự kiến</span>
          <strong>{plan.effective_consumption_wh_per_km.toFixed(0)} Wh/km</strong>
        </div>
        <div>
          <span>SOC đến đích</span>
          <strong>{plan.final_arrival_soc_percent.toFixed(1)}%</strong>
        </div>
        <div>
          <span>Nguồn môi trường</span>
          <strong>
            {environment.status === "LIVE"
              ? "Open-Meteo"
              : environment.status === "CACHED"
                ? "Open-Meteo cache"
                : environment.status === "WEB_SEARCH"
                  ? "OpenAI web search"
                  : "Giả định an toàn"}
          </strong>
        </div>
        <div>
          <span>Route cập nhật</span>
          <strong>
            {plan.route.retrieved_at
              ? new Date(plan.route.retrieved_at).toLocaleString("vi-VN")
              : "Không rõ"}
          </strong>
        </div>
        <div>
          <span>Thời tiết cập nhật</span>
          <strong>{new Date(environment.weather_provenance.retrieved_at).toLocaleString("vi-VN")}</strong>
        </div>
        <div>
          <span>Minh bạch trạng thái trạm</span>
          <strong>Không có availability từng cổng realtime</strong>
        </div>
      </article>
    </>
  );
}
