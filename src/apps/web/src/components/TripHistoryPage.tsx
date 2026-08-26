import type { TripHistoryItem } from "../lib/types";

function durationLabel(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const remainder = Math.round(minutes % 60);
  return hours ? `${hours} giờ ${remainder} phút` : `${remainder} phút`;
}

export function TripHistoryPage({ trips, loading, error, onRetry }: {
  trips: TripHistoryItem[];
  loading: boolean;
  error: string;
  onRetry: () => void;
}) {
  return (
    <section className="trip-history-page" id="top">
      <header className="trip-history-header">
        <div><small>HÀNH TRÌNH ĐÃ CHỌN</small><h1>Lịch sử chuyến đi</h1></div>
        <span>{trips.length} chuyến</span>
      </header>
      {loading ? <div className="history-state">Đang tải lịch sử…</div> : null}
      {!loading && error ? <div className="history-state history-state--error"><p>{error}</p><button type="button" onClick={onRetry}>Thử lại</button></div> : null}
      {!loading && !error && trips.length === 0 ? <div className="history-state"><strong>Chưa có hành trình đã chọn</strong><p>Hành trình sẽ xuất hiện tại đây sau khi bạn chọn và bắt đầu theo dõi.</p></div> : null}
      {!loading && !error ? <div className="trip-history-list">
        {trips.map((trip) => {
          const plan = trip.selected_plan;
          return <article className="trip-history-card" key={trip.trip_id}>
            <header>
              <div><small>{new Date(trip.selected_at).toLocaleString("vi-VN")}</small><strong>{trip.origin.address}</strong><span aria-hidden="true">→</span><strong>{trip.destination.address}</strong></div>
              <span className="history-status">{trip.status === "ACTIVE" ? "Đang theo dõi" : trip.status}</span>
            </header>
            <div className="history-metrics">
              <div><span>SOC ban đầu</span><strong>{trip.initial_soc.value_percent.toFixed(1)}%</strong></div>
              <div><span>SOC đến đích</span><strong>{plan.final_arrival_soc_percent.toFixed(1)}%</strong></div>
              <div><span>Quãng đường</span><strong>{plan.route.distance_km.toFixed(1)} km</strong></div>
              <div><span>Thời gian</span><strong>{durationLabel(plan.route.duration_min)}</strong></div>
            </div>
            <div className="history-stations">
              <h2>{plan.charging_stops.length ? `${plan.charging_stops.length} trạm sạc` : "Không cần dừng sạc"}</h2>
              {plan.charging_stops.map((stop, index) => <div className="history-station" key={`${stop.station_id}-${index}`}>
                <span className="history-station-index">{index + 1}</span>
                <div className="history-station-main"><strong>{stop.name}</strong><small>{stop.address || `${stop.lat.toFixed(5)}, ${stop.lon.toFixed(5)}`}</small><p>{stop.connector_type} · {stop.max_power_kw} kW · {stop.port_count} cổng · sạc {stop.charge_duration_min.toFixed(0)} phút</p></div>
                <div className="history-station-soc"><span>Đến trạm <strong>{stop.arrival_soc_percent.toFixed(1)}%</strong></span><span>Rời trạm <strong>{stop.departure_soc_percent.toFixed(1)}%</strong></span></div>
              </div>)}
            </div>
          </article>;
        })}
      </div> : null}
    </section>
  );
}
