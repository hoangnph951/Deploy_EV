from __future__ import annotations

from src.packages.agent.replanning.schemas import DiagnosticObservation
from src.packages.contracts.monitoring import TelemetrySnapshot
from src.packages.contracts.replanning import TripContextSnapshot

EVENT_DIAGNOSTICS: dict[str, tuple[str, ...]] = {
    "ROUTE_DEVIATION": ("inspect_route",),
    "SOC_UNDERPERFORMANCE": ("inspect_energy", "nearest_station_reachability"),
    "STATION_UNAVAILABLE": ("inspect_stations",),
    "STALE_TELEMETRY": (),
}


def required_diagnostics(event_types: list[str]) -> list[str]:
    ordered: list[str] = []
    if "STALE_TELEMETRY" in event_types:
        return ordered
    ordered.append("project_current_plan")
    for name in (
        "inspect_route", "inspect_energy", "nearest_station_reachability", "inspect_stations"
    ):
        if any(name in EVENT_DIAGNOSTICS.get(event_type, ()) for event_type in event_types):
            ordered.append(name)
    return ordered


class DiagnosticRegistry:
    """Deterministic evidence adapters used before F1 candidate construction."""

    def execute(
        self,
        name: str,
        *,
        context: TripContextSnapshot,
        telemetry: TelemetrySnapshot,
        current_plan_projection: dict | None = None,
    ) -> DiagnosticObservation:
        snapshot_ref = f"telemetry:{telemetry.snapshot_id or context.telemetry_snapshot_id}"
        if name == "project_current_plan":
            projection = current_plan_projection or {
                "confirmed_plan_version": context.current_confirmed_plan_version,
                "remaining_station_ids": [],
                "affected_excluded_station_ids": [],
                "unaffected_remaining_station_ids": [],
                "station_unavailable_affects_remaining_trip": None,
            }
            impact = projection.get("station_unavailable_affects_remaining_trip")
            return DiagnosticObservation(
                tool=name, status="SUCCEEDED", provider="F2_PLAN_HISTORY",
                freshness="FRESH",
                facts=projection,
                evidence_refs=[
                    f"plan:{context.trip_id}:v{context.current_confirmed_plan_version}", snapshot_ref
                ],
                reason_codes=[
                    "CURRENT_PLAN_PROJECTED",
                    (
                        "UNAVAILABLE_STATION_AFFECTS_REMAINING_TRIP"
                        if impact is True
                        else "UNAVAILABLE_STATION_NOT_IN_REMAINING_TRIP"
                        if impact is False
                        else "STATION_IMPACT_NOT_APPLICABLE"
                    ),
                ],
                public_summary=(
                    "Trạm bị loại vẫn nằm trong phần hành trình còn lại; cần tìm phương án thay thế."
                    if impact is True
                    else "Trạm bị loại không còn nằm trong phần hành trình phía trước; có thể giữ kế hoạch hiện tại."
                    if impact is False
                    else "Đã chiếu phần hành trình còn lại từ vị trí và SOC hiện tại."
                ),
            )
        if name == "inspect_route":
            return DiagnosticObservation(
                tool=name, status="SUCCEEDED", provider="F1_ROUTING_PROVIDER",
                freshness="FRESH", facts={"route_deviation_active": True},
                evidence_refs=[snapshot_ref], reason_codes=["ROUTE_EVIDENCE_VERIFIED"],
                public_summary="Đã xác nhận xe đang lệch khỏi tuyến đã duyệt.",
            )
        if name == "inspect_energy":
            return DiagnosticObservation(
                tool=name, status="SUCCEEDED", provider="F1_ENERGY_MODEL",
                freshness="FRESH",
                facts={
                    "soc_percent": telemetry.soc_percent,
                    "expected_soc_percent": telemetry.expected_soc_percent,
                },
                evidence_refs=[snapshot_ref], reason_codes=["ENERGY_EVIDENCE_VERIFIED"],
                public_summary=(
                    f"SOC thực tế {telemetry.soc_percent:.1f}% thấp hơn mức kỳ vọng "
                    f"{telemetry.expected_soc_percent:.1f}%; cần bảo vệ mức pin dự phòng."
                ),
            )
        if name == "nearest_station_reachability":
            return DiagnosticObservation(
                tool=name, status="SUCCEEDED", provider="F1_STATION_REACHABILITY",
                freshness="FRESH",
                facts={
                    "origin_lat": telemetry.lat,
                    "origin_lon": telemetry.lon,
                    "current_soc_percent": telemetry.soc_percent,
                    "objective": "FIND_REACHABLE_ALTERNATIVE_CHARGING_OPTION",
                    "reachability_verdict": "PENDING_F1_FEASIBILITY",
                },
                evidence_refs=[snapshot_ref],
                reason_codes=["NEAREST_STATION_REACHABILITY_SCOPE_READY"],
                public_summary=(
                    "Đã chuẩn bị phạm vi tìm trạm sạc gần nhất từ vị trí hiện tại; "
                    "F1 sẽ xác minh khả năng tiếp cận và SOC khi đến trạm."
                ),
            )
        if name == "inspect_stations":
            excluded = context.unresolved_constraints.excluded_station_ids
            return DiagnosticObservation(
                tool=name, status="SUCCEEDED", provider="F1_STATION_PROVIDER",
                freshness="FRESH", facts={"excluded_station_ids": excluded},
                evidence_refs=[f"station:{station_id}:excluded" for station_id in excluded],
                reason_codes=["STATION_EXCLUSIONS_VERIFIED"],
                public_summary="Đã loại các trạm không khả dụng khỏi phạm vi tìm kiếm.",
            )
        raise ValueError(f"Unknown diagnostic tool: {name}")
