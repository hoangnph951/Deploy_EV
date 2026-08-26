from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from src.packages.contracts.monitoring import MonitoringEvent, TelemetrySnapshot


class MonitoringService:
    ROUTE_DEVIATION_KM = 2.0
    SOC_UNDERPERFORMANCE_PERCENT = 5.0
    TELEMETRY_STALE_SECONDS = 60.0

    def evaluate(
        self,
        telemetry: TelemetrySnapshot,
        *,
        profile: str,
        station_id: str | None = None,
        already_emitted: set[str] | None = None,
    ) -> list[MonitoringEvent]:
        emitted = already_emitted or set()
        events: list[MonitoringEvent] = []

        if telemetry.age_seconds > self.TELEMETRY_STALE_SECONDS:
            return self._new_event(
                telemetry,
                "STALE_TELEMETRY",
                "CRITICAL",
                "telemetry_stale_after_seconds",
                self.TELEMETRY_STALE_SECONDS,
                telemetry.age_seconds,
                ["TELEMETRY_TOO_OLD"],
                emitted,
            )

        route_deviation = telemetry.distance_to_route_km
        if route_deviation > self.ROUTE_DEVIATION_KM:
            events += self._new_event(
                telemetry,
                "ROUTE_DEVIATION",
                "WARNING",
                "route_deviation_km_threshold",
                self.ROUTE_DEVIATION_KM,
                route_deviation,
                ["VEHICLE_OFF_CONFIRMED_ROUTE"],
                emitted,
            )

        soc_gap = telemetry.expected_soc_percent - telemetry.actual_soc_percent
        if soc_gap > self.SOC_UNDERPERFORMANCE_PERCENT:
            events += self._new_event(
                telemetry,
                "SOC_UNDERPERFORMANCE",
                "CRITICAL",
                "soc_underperformance_threshold_percent",
                self.SOC_UNDERPERFORMANCE_PERCENT,
                soc_gap,
                ["ACTUAL_SOC_BELOW_EXPECTED"],
                emitted,
            )

        if profile in {"STATION_UNAVAILABLE", "NO_FEASIBLE_ALTERNATIVE"} and station_id:
            station_events = self._new_event(
                telemetry,
                "STATION_UNAVAILABLE",
                "CRITICAL",
                "station_availability",
                None,
                None,
                ["PLANNED_STATION_UNAVAILABLE"],
                emitted,
            )
            for item in station_events:
                item.station_id = station_id
            events += station_events
        return events

    @staticmethod
    def _new_event(
        telemetry: TelemetrySnapshot,
        event_type: str,
        severity: str,
        threshold_name: str,
        threshold_value: float | None,
        actual_value: float | None,
        reason_codes: list[str],
        emitted: set[str],
    ) -> list[MonitoringEvent]:
        if event_type in emitted:
            return []
        event_id = str(uuid5(NAMESPACE_URL, f"{telemetry.simulation_run_id}:{event_type}"))
        return [
            MonitoringEvent(
                event_id=event_id,
                event_type=event_type,
                severity=severity,
                threshold_name=threshold_name,
                threshold_value=threshold_value,
                actual_value=actual_value,
                telemetry_event_id=telemetry.event_id,
                scenario_id=telemetry.scenario_id,
                simulation_run_id=telemetry.simulation_run_id,
                tick=telemetry.tick,
                reason_codes=reason_codes,
            )
        ]

