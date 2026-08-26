import { useEffect, useRef, useState } from "react";

import { getGoongMaps, getGoongStyleUrl, goongMapsConfigured } from "../lib/goongMaps";
import type { PlaceSelection, PlanProposal, SimulationState } from "../lib/types";

type Props = {
  plan: PlanProposal | null;
  origin: PlaceSelection | null;
  destination: PlaceSelection | null;
  telemetry?: SimulationState["telemetry"];
};

function popupContent(title: string, lines: string[]): HTMLElement {
  const container = document.createElement("div");
  container.className = "goong-map-popup";
  const heading = document.createElement("strong");
  heading.textContent = title;
  container.appendChild(heading);
  for (const line of lines) {
    const row = document.createElement("div");
    row.textContent = line;
    container.appendChild(row);
  }
  return container;
}

export function TripPlanMap({ plan, origin, destination, telemetry }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<any>(null);
  const markersRef = useRef<any[]>([]);
  const [mapReady, setMapReady] = useState(false);
  const [mapLoading, setMapLoading] = useState(true);
  const [mapError, setMapError] = useState("");

  useEffect(() => {
    if (!goongMapsConfigured()) {
      setMapError("Thiếu GOONG_MAPTILES_KEY nên chưa thể hiển thị bản đồ Goong.");
      setMapLoading(false);
      return;
    }
    if (!containerRef.current) return;

    try {
      const goongjs = getGoongMaps();
      if (!goongjs.supported()) {
        setMapError("Trình duyệt không hỗ trợ WebGL để hiển thị bản đồ Goong.");
        setMapLoading(false);
        return;
      }
      let disposed = false;
      let styleLoaded = false;
      const map = new goongjs.Map({
        container: containerRef.current,
        style: getGoongStyleUrl(),
        center: [105.83991, 21.028],
        zoom: 9,
      });
      mapRef.current = map;
      map.addControl(new goongjs.NavigationControl(), "top-right");

      // `load` waits for every source tile. The route is our own GeoJSON layer,
      // so it can be attached as soon as the style exists, even while base
      // map tiles continue loading.
      const handleStyleLoad = () => {
        if (disposed) return;
        styleLoaded = true;
        map.resize();
        setMapReady(true);
        setMapLoading(false);
        setMapError("");
        requestAnimationFrame(() => {
          if (!disposed) map.resize();
        });
      };
      map.on("style.load", handleStyleLoad);

      map.on("error", (event: { error?: { message?: string } }) => {
        if (disposed || !event.error) return;
        setMapLoading(false);
        setMapError(event.error.message || "Không tải được bản đồ Goong.");
      });

      const watchdog = window.setTimeout(() => {
        if (disposed || styleLoaded) return;
        setMapLoading(false);
        setMapError(
          "Goong chưa tải xong style. Hãy kiểm tra giới hạn URL của Maptiles Key có cho phép domain/port localhost đang chạy.",
        );
      }, 12_000);

      return () => {
        disposed = true;
        window.clearTimeout(watchdog);
        markersRef.current.forEach((marker) => marker.remove());
        markersRef.current = [];
        if (mapRef.current === map) mapRef.current = null;
        map.remove();
      };
    } catch (error) {
      setMapLoading(false);
      setMapError(error instanceof Error ? error.message : "Không tải được bản đồ Goong.");
    }
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map) return;
    const goongjs = getGoongMaps();

    markersRef.current.forEach((marker) => marker.remove());
    markersRef.current = [];
    if (map.getLayer("trip-route")) map.removeLayer("trip-route");
    if (map.getSource("trip-route")) map.removeSource("trip-route");

    const bounds = new goongjs.LngLatBounds();
    let pointCount = 0;
    const addMarker = (
      coordinates: [number, number],
      label: string,
      title: string,
      lines: string[],
      color: string,
    ) => {
      const markerElement = document.createElement("button");
      markerElement.type = "button";
      markerElement.className = "goong-trip-marker";
      markerElement.textContent = label;
      markerElement.style.backgroundColor = color;
      markerElement.setAttribute("aria-label", title);
      const popup = new goongjs.Popup({ offset: 18 }).setDOMContent(popupContent(title, lines));
      const marker = new goongjs.Marker({ element: markerElement })
        .setLngLat(coordinates)
        .setPopup(popup)
        .addTo(map);
      markersRef.current.push(marker);
      bounds.extend(coordinates);
      pointCount += 1;
    };

    const routeCoordinates = plan?.route.polyline.map(([lat, lng]) => [lng, lat] as [number, number]) ?? [];
    if (routeCoordinates.length > 1) {
      map.addSource("trip-route", {
        type: "geojson",
        data: {
          type: "Feature",
          properties: {},
          geometry: { type: "LineString", coordinates: routeCoordinates },
        },
      });
      map.addLayer({
        id: "trip-route",
        type: "line",
        source: "trip-route",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": plan?.risk_assessment.is_feasible ? "#1473e6" : "#dc2626",
          "line-width": 6,
          "line-opacity": 0.95,
        },
      });
      routeCoordinates.forEach((coordinate) => bounds.extend(coordinate));
      pointCount += routeCoordinates.length;
    }

    const routeOrigin = routeCoordinates[0];
    const routeDestination = routeCoordinates[routeCoordinates.length - 1];
    const originPosition = routeOrigin ?? (origin ? [origin.lng, origin.lat] as [number, number] : null);
    const destinationPosition = routeDestination ?? (
      destination ? [destination.lng, destination.lat] as [number, number] : null
    );

    if (originPosition) {
      addMarker(originPosition, "A", "Điểm xuất phát", [origin?.address ?? "Đã chọn"], "#0c7c59");
    }
    if (destinationPosition) {
      addMarker(destinationPosition, "B", "Điểm đến", [destination?.address ?? "Đã chọn"], "#4338ca");
    }

    plan?.charging_stops.forEach((stop, index) => {
      addMarker(
        [stop.lon, stop.lat],
        `${index + 1}`,
        stop.name,
        [
          stop.address,
          `${stop.port_count} cổng · ${stop.max_power_kw} kW · ${stop.connector_type}`,
          `SOC ${stop.arrival_soc_percent.toFixed(1)}% → ${stop.departure_soc_percent.toFixed(1)}%`,
          `Metadata VinFast: ${stop.station_status}`,
        ],
        "#f59e0b",
      );
    });

    if (telemetry) {
      addMarker(
        [telemetry.lon, telemetry.lat], "🚗", "Xe mô phỏng",
        [`SOC ${telemetry.soc_percent.toFixed(1)}%`, `${telemetry.speed_kph.toFixed(0)} km/h`, telemetry.freshness],
        telemetry.freshness === "STALE" ? "#d97706" : "#7c3aed",
      );
    }

    if (pointCount > 1) {
      map.fitBounds(bounds, { padding: 58, maxZoom: 14 });
    } else if (pointCount === 1) {
      map.setCenter(bounds.getCenter());
      map.setZoom(13);
    }
  }, [destination, mapReady, origin, plan, telemetry]);

  return (
    <article className="map-card goong-map-card">
      {mapError ? <div className="goong-map-error">{mapError}</div> : null}
      <div className="goong-map-shell">
        <div ref={containerRef} className="goong-route-map" aria-label="Bản đồ Goong của hành trình" />
        <div className="map-overlay-title">
          <strong>Lộ trình VGo</strong>
          <span>Goong · VinFast Locator</span>
        </div>
        {plan ? (
          <div className="map-plan-badges">
            <span>PLAN v{plan.version}</span>
            <span className="map-status-badge">{plan.status}</span>
            <span className={`map-risk-badge map-risk-badge--${plan.risk_assessment.level.toLowerCase()}`}>
              {plan.risk_assessment.level.replace(/_/g, " ")}
            </span>
          </div>
        ) : null}
        {mapLoading && !mapError ? (
          <div className="goong-map-loading" role="status">Đang tải bản đồ Goong…</div>
        ) : null}
        <p className="source-note">
          © Goong · Tuyến {plan?.route.provider ?? "chưa tính"} · Trạm VinFast Locator
        </p>
      </div>
    </article>
  );
}
