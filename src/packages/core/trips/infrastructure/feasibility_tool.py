from __future__ import annotations

from src.packages.contracts.trips import AssumptionSnapshot, RiskAssessment
from src.packages.core.trips.infrastructure.energy_tool import EnergySimulationResult


class FeasibilityTool:
    """Deterministic safety boundary check for EV trip plans."""

    def evaluate(
        self,
        energy_result: EnergySimulationResult,
        assumptions: AssumptionSnapshot,
        initial_soc_percent: float,
        required_connector: str = "CCS2",
        no_compatible_connector: bool = False,
        detour_distance_exceeded: bool = False,
        detour_time_exceeded: bool = False,
    ) -> RiskAssessment:
        reserve_soc = assumptions.reserve_soc_percent
        reasons: list[str] = []
        reason_codes: list[str] = []
        risk_score = 0.0

        for leg in energy_result.legs:
            if leg.arrival_soc_percent < reserve_soc:
                if leg.arrival_soc_percent < 0:
                    reasons.append(
                        f"Chặng đến '{leg.to_name}' dài {leg.distance_km:.1f} km và cần khoảng "
                        f"{leg.energy_consumed_kwh:.1f} kWh. Pin sẽ cạn trước khi đến nơi, "
                        f"nên cần điểm sạc trung gian để duy trì mức dự phòng {reserve_soc:.1f}%."
                    )
                else:
                    reasons.append(
                        f"Mức pin dự kiến khi đến '{leg.to_name}' chỉ còn "
                        f"{leg.arrival_soc_percent:.1f}%, thấp hơn mức pin dự phòng "
                        f"tối thiểu ({reserve_soc:.1f}%)."
                    )
                reason_codes.append("SOC_BELOW_RESERVE_15")

        if initial_soc_percent < reserve_soc:
            reasons.append(
                f"Mức pin khởi hành ({initial_soc_percent:.1f}%) thấp hơn "
                f"mức dự phòng ({reserve_soc:.1f}%)."
            )
            reason_codes.append("INITIAL_SOC_BELOW_RESERVE")

        if energy_result.unreachable_next_station:
            reasons.append("Không thể tiếp cận trạm tiếp theo mà vẫn duy trì SOC dự phòng.")
            reason_codes.append("UNREACHABLE_NEXT_STATION")

        for stop in energy_result.charging_stops:
            if required_connector not in stop.connector_type:
                reasons.append(
                    f"Trạm '{stop.name}' không hỗ trợ connector {required_connector} của xe."
                )
                reason_codes.append("NO_COMPATIBLE_CONNECTOR")

        if no_compatible_connector and energy_result.final_arrival_soc_percent < reserve_soc:
            reasons.append(
                f"Không tìm thấy trạm {required_connector} tương thích trên hành lang tuyến."
            )
            reason_codes.append("NO_COMPATIBLE_CONNECTOR")

        if detour_distance_exceeded:
            reasons.append(
                "Các phương án qua trạm đã kiểm tra đều làm quãng đường tăng quá giới hạn 10 km."
            )
            reason_codes.append("DETOUR_DISTANCE_EXCEEDED")

        if detour_time_exceeded:
            reasons.append(
                "Các phương án qua trạm đã kiểm tra đều làm thời gian lái tăng quá giới hạn 15 phút."
            )
            reason_codes.append("DETOUR_TIME_EXCEEDED")

        critical_codes = {
            "SOC_BELOW_RESERVE_15",
            "INITIAL_SOC_BELOW_RESERVE",
            "NO_COMPATIBLE_CONNECTOR",
            "UNREACHABLE_NEXT_STATION",
            "DETOUR_DISTANCE_EXCEEDED",
            "DETOUR_TIME_EXCEEDED",
        }
        if critical_codes.intersection(reason_codes):
            return RiskAssessment(
                verdict="INFEASIBLE",
                level="INFEASIBLE",
                is_feasible=False,
                reasons=reasons,
                reason_codes=list(dict.fromkeys(reason_codes)),
                risk_score=100.0,
            )

        has_stale = False
        for stop in energy_result.charging_stops:
            if stop.freshness == "STALE":
                has_stale = True
                reasons.append(
                    f"Dữ liệu trạm '{stop.name}' đã cũ (>24h); cần kiểm tra trước khi đến."
                )
                if "STALE_STATION_DATA" not in reason_codes:
                    risk_score += 35.0
                reason_codes.append("STALE_STATION_DATA")
            if stop.station_status == "BUSY":
                reasons.append(
                    f"VinFast đang ghi nhận metadata trạm '{stop.name}' là BUSY; "
                    "đây không phải availability từng cổng."
                )
                if "STATION_BUSY" not in reason_codes:
                    risk_score += 20.0
                reason_codes.append("STATION_BUSY")
            if stop.station_status == "UNVERIFIED":
                reasons.append(
                    f"Trạm '{stop.name}' được tìm từ web fallback và chưa có trạng thái vận hành realtime."
                )
                if "UNVERIFIED_STATION_DATA" not in reason_codes:
                    risk_score += 40.0
                reason_codes.append("UNVERIFIED_STATION_DATA")

        if reserve_soc < energy_result.final_arrival_soc_percent < reserve_soc + 5.0:
            reasons.append(
                f"SOC tại đích ({energy_result.final_arrival_soc_percent:.1f}%) "
                "đang sát mức dự phòng."
            )
            reason_codes.append("TIGHT_ENERGY_MARGIN")
            risk_score += 25.0

        if has_stale or risk_score >= 50.0:
            level = "HIGH_RISK" if risk_score >= 60.0 else "MEDIUM_RISK"
        elif risk_score > 0:
            level = "MEDIUM_RISK"
        else:
            level = "LOW_RISK"
            reasons.append(
                "SOC tại mọi điểm đến đều không thấp hơn mức dự phòng theo policy."
            )

        return RiskAssessment(
            verdict="RISKY" if risk_score > 0 else "FEASIBLE",
            level=level,
            is_feasible=True,
            reasons=reasons,
            reason_codes=list(dict.fromkeys(reason_codes)),
            risk_score=min(100.0, risk_score),
        )
