import type { PlanProposal } from "../lib/types";

type Props = {
  plan: PlanProposal;
  initialSoc: number;
};

export function SocChart({ plan }: Props) {
  const chartData = plan.soc_points;
  const reserveSoc = plan.assumptions.reserve_soc_percent;
  const svgWidth = 720;
  const svgHeight = 260;
  const padding = { top: 24, right: 34, bottom: 42, left: 48 };
  const plotWidth = svgWidth - padding.left - padding.right;
  const plotHeight = svgHeight - padding.top - padding.bottom;
  const totalDistance = Math.max(1, plan.route.distance_km);
  const getX = (distance: number) => padding.left + (distance / totalDistance) * plotWidth;
  const getY = (soc: number) => padding.top + (1 - Math.max(0, Math.min(100, soc)) / 100) * plotHeight;
  const path = chartData
    .map((point, index) => `${index === 0 ? "M" : "L"} ${getX(point.distance_km)} ${getY(point.soc_percent)}`)
    .join(" ");

  return (
    <article className="soc-chart-card">
      <div className="soc-chart-header">
        <div>
          <p className="panel-kicker">Backend energy model</p>
          <h3 className="section-subtitle">SOC dự kiến theo quãng đường</h3>
        </div>
        <span className="reserve-legend">Ngưỡng dự phòng {reserveSoc}%</span>
      </div>
      <div className="soc-svg-wrapper">
        <svg viewBox={`0 0 ${svgWidth} ${svgHeight}`} className="soc-svg" role="img" aria-label="Biểu đồ SOC dự kiến">
          {[0, 25, 50, 75, 100].map((value) => (
            <g key={value}>
              <line x1={padding.left} y1={getY(value)} x2={svgWidth - padding.right} y2={getY(value)} stroke="#dbe3ef" />
              <text x={padding.left - 9} y={getY(value) + 4} textAnchor="end" fontSize="11">{value}%</text>
            </g>
          ))}
          <line
            x1={padding.left}
            y1={getY(reserveSoc)}
            x2={svgWidth - padding.right}
            y2={getY(reserveSoc)}
            stroke="#dc2626"
            strokeWidth="2"
            strokeDasharray="6 5"
          />
          <path d={path} fill="none" stroke="#1677ff" strokeWidth="4" strokeLinejoin="round" />
          {chartData.map((point, index) => (
            <g key={`${point.kind}-${point.distance_km}-${index}`}>
              <circle
                cx={getX(point.distance_km)}
                cy={getY(point.soc_percent)}
                r="5"
                fill={point.soc_percent < reserveSoc ? "#dc2626" : point.kind === "DEPARTURE" ? "#059669" : "#1677ff"}
                stroke="#fff"
                strokeWidth="2"
              >
                <title>{point.label}: {point.soc_percent.toFixed(1)}% tại {point.distance_km.toFixed(1)} km</title>
              </circle>
            </g>
          ))}
          <text x={padding.left} y={svgHeight - 12} fontSize="11">0 km</text>
          <text x={svgWidth - padding.right} y={svgHeight - 12} textAnchor="end" fontSize="11">{totalDistance.toFixed(0)} km</text>
        </svg>
      </div>
      <div className="soc-point-list">
        {chartData.map((point, index) => (
          <span key={`${point.label}-${index}`}><strong>{point.soc_percent.toFixed(1)}%</strong> {point.label}</span>
        ))}
      </div>
    </article>
  );
}
