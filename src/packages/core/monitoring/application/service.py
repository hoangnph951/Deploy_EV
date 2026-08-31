from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import RLock
from uuid import uuid4

from src.packages.contracts.monitoring import (
    MonitoringEvent,
    MonitoringThresholds,
    SimulationDecisionRequest,
    SimulationState,
    SimulatorStartRequest,
    TelemetrySnapshot,
)
from src.packages.contracts.trips import PlanProposal
from src.packages.core.monitoring.application.periodic_risk import PeriodicRiskEvaluator
from src.packages.core.monitoring.domain.geometry import haversine_km, point_along_polyline
from src.packages.core.monitoring.domain.risk import SOCRiskState
from src.packages.core.monitoring.domain.soc import expected_soc_at_distance
from src.packages.core.trips.application.errors import AppError, ForbiddenError, NotFoundError


def _offset_lat(lat: float, km: float) -> float:
    return lat + km / 110.574


@dataclass
class _Session:
    trip_id: str
    plan: PlanProposal
    request: SimulatorStartRequest
    scenario: str
    status: str = "RUNNING"
    tick_count: int = 0
    distance_km: float = 0.0
    telemetry: TelemetrySnapshot | None = None
    events: list[MonitoringEvent] = field(default_factory=list)
    unavailable_station_ids: list[str] = field(default_factory=list)
    replan_required: bool = False
    anomaly_emitted: bool = False
    speed_multiplier: float = 1.0
    estimated_duration_seconds: int = 0
    soc_risk: SOCRiskState = field(default_factory=SOCRiskState.empty)


class MonitoringEvaluator:
    """Pure threshold gate. Equality is normal; only a strict exceedance creates an event."""

    def __init__(self, thresholds: MonitoringThresholds | None = None):
        self.thresholds = thresholds or MonitoringThresholds()

    def classify(
        self, *, off_route_distance_km: float = 0, soc_deficit_percent: float = 0,
        silent_seconds: float = 0, station_unavailable: bool = False,
    ) -> str:
        if station_unavailable:
            return "STATION_UNAVAILABLE"
        if off_route_distance_km > self.thresholds.max_off_route_distance_km:
            return "ROUTE_DEVIATION"
        if soc_deficit_percent > self.thresholds.max_soc_drop_deviation_percent:
            return "SOC_UNDERPERFORMANCE"
        if silent_seconds > self.thresholds.max_telemetry_silent_seconds:
            return "STALE_TELEMETRY"
        return "NORMAL"


class MonitoringSimulatorService:
    """Deterministic demo simulator. A tick is advanced by the client, not a background worker."""

    def __init__(self, repository, thresholds: MonitoringThresholds | None = None):
        self._repository = repository
        self._thresholds = thresholds or MonitoringThresholds()
        self._evaluator = MonitoringEvaluator(self._thresholds)
        self._soc_risk_evaluator = PeriodicRiskEvaluator(
            event_threshold=-self._thresholds.max_soc_drop_deviation_percent
        )
        self._sessions: dict[str, _Session] = {}
        self._lock = RLock()

    def start(self, trip_id: str, owner_id: str, request: SimulatorStartRequest) -> SimulationState:
        trip = self._owned_trip(trip_id, owner_id)
        records = self._repository.get_plan_versions(trip_id)
        record = (
            next((item for item in records if item.id == request.plan_id), None)
            if request.plan_id else None
        )
        if record is None:
            raise AppError(
                "PLAN_REQUIRED", 409,
                "Hãy chọn đúng phiên bản hành trình đã được lưu trước khi bắt đầu mô phỏng.",
            )
        if record.status != "CONFIRMED":
            raise AppError(
                "PLAN_NOT_CONFIRMED", 409,
                "Hành trình phải được bạn xác nhận trước khi bắt đầu mô phỏng.",
                {"plan_id": record.id, "plan_version": record.version, "status": record.status},
            )
        if request.plan is not None:
            plan = request.plan
            if plan.trip_id != trip_id or (request.plan_id and plan.plan_id != request.plan_id):
                raise AppError("PLAN_MISMATCH", 409, "Proposal đã chọn không thuộc chuyến đi này.")
            if plan.version != record.version:
                raise AppError(
                    "PLAN_MISMATCH", 409,
                    "Phiên bản hành trình hiển thị không khớp dữ liệu đã xác nhận.",
                )
        else:
            if record is None or not record.proposal_json:
                raise AppError("PLAN_REQUIRED", 409, "Hãy lập kế hoạch trước khi bắt đầu mô phỏng.")
            import json
            plan = PlanProposal.model_validate(json.loads(record.proposal_json))
        if len(plan.route.polyline) < 2:
            raise AppError("ROUTE_REQUIRED", 409, "Kế hoạch chưa có polyline để mô phỏng.")
        multi_events = set(request.scenario_events) or {
            "ROUTE_DEVIATION", "SOC_UNDERPERFORMANCE", "STATION_UNAVAILABLE",
        }
        needs_station = request.scenario == "STATION_UNAVAILABLE" or (
            request.scenario == "MULTI_EVENT" and "STATION_UNAVAILABLE" in multi_events
        )
        if needs_station and not plan.charging_stops:
            raise AppError(
                "STATION_REQUIRED", 409,
                "Kịch bản có sự cố trạm cần một proposal có ít nhất một trạm sạc.",
            )
        scenario = request.scenario
        if scenario == "RANDOM":
            rng = random.Random(request.seed)
            if rng.random() >= request.unhappy_probability:
                scenario = "NORMAL"
            else:
                candidates = [
                    candidate
                    for candidate in self._random_scenarios(bool(plan.charging_stops))
                    if candidate != "NORMAL"
                ]
                scenario = rng.choice(candidates)
        speed_multiplier, estimated_seconds = self._simulation_pacing(
            plan.route.distance_km, request.speed_multiplier
        )
        session = _Session(
            trip_id=trip.id, plan=plan, request=request, scenario=scenario,
            speed_multiplier=speed_multiplier, estimated_duration_seconds=estimated_seconds,
        )
        with self._lock:
            self._sessions[trip_id] = session
        return self._state(session)

    def tick(self, trip_id: str, owner_id: str) -> SimulationState:
        self._owned_trip(trip_id, owner_id)
        with self._lock:
            session = self._require_session(trip_id)
            if session.status != "RUNNING":
                return self._state(session)
            session.tick_count += 1
            route_distance = max(session.plan.route.distance_km, 0.01)
            step_km = 0.06 * session.request.tick_interval_seconds * session.speed_multiplier
            unavailable_station = None
            if session.scenario == "STATION_UNAVAILABLE" and session.plan.charging_stops:
                unavailable_station = self._station_warning_before_move(
                    session.plan,
                    current_distance_km=session.distance_km,
                    next_step_km=step_km,
                )

            # An availability feed is checked before moving the vehicle into the
            # affected station. Pausing this tick also guarantees that a large
            # simulation step cannot jump past the stop before F4 receives it.
            if unavailable_station is None:
                session.distance_km = min(route_distance, session.distance_km + step_km)
            progress = session.distance_km / route_distance
            lat, lon = self._point_at(session.plan.route.polyline, progress)
            expected_soc = self._expected_soc(session.plan, session.distance_km)
            actual_soc = expected_soc
            freshness = "FRESH"
            recorded_at = datetime.now(UTC)
            telemetry_snapshot_id = str(uuid4())
            distance_to_route_km = 0.0
            age_seconds = 0.0
            trigger = progress >= 0.35 and not session.anomaly_emitted

            if unavailable_station is not None and not session.anomaly_emitted:
                session.unavailable_station_ids.append(unavailable_station.station_id)
                self._emit(
                    session,
                    "STATION_UNAVAILABLE",
                    f"Trạm {unavailable_station.name} không khả dụng (mô phỏng).",
                    {
                        "station_id": unavailable_station.station_id,
                        "station_name": unavailable_station.name,
                        "station_distance_km": unavailable_station.distance_from_origin_km,
                        "vehicle_distance_km": round(session.distance_km, 3),
                        "distance_to_station_km": round(
                            unavailable_station.distance_from_origin_km - session.distance_km, 3
                        ),
                    },
                    telemetry_snapshot_id=telemetry_snapshot_id,
                    occurred_at=recorded_at,
                )
            elif trigger and session.scenario == "MULTI_EVENT":
                selected_events = set(session.request.scenario_events) or {
                    "ROUTE_DEVIATION", "SOC_UNDERPERFORMANCE", "STATION_UNAVAILABLE",
                }
                if "ROUTE_DEVIATION" in selected_events:
                    distance_to_route_km = self._thresholds.max_off_route_distance_km + 0.01
                    lat = _offset_lat(lat, distance_to_route_km)
                    self._emit(session, "ROUTE_DEVIATION", "Xe đã lệch khỏi tuyến dự kiến.", {
                        "off_route_distance_km": distance_to_route_km,
                        "threshold_km": self._thresholds.max_off_route_distance_km,
                    }, telemetry_snapshot_id=telemetry_snapshot_id, occurred_at=recorded_at)
                if "SOC_UNDERPERFORMANCE" in selected_events:
                    soc_deficit_percent = self._thresholds.max_soc_drop_deviation_percent + 0.1
                    actual_soc = expected_soc - soc_deficit_percent
                    self._emit(session, "SOC_UNDERPERFORMANCE", "SOC thực tế thấp hơn mức dự kiến.", {
                        "soc_deficit_percent": soc_deficit_percent,
                        "threshold_percent": self._thresholds.max_soc_drop_deviation_percent,
                    }, telemetry_snapshot_id=telemetry_snapshot_id, occurred_at=recorded_at)
                if "STATION_UNAVAILABLE" in selected_events:
                    station = next((
                        stop for stop in sorted(
                            session.plan.charging_stops,
                            key=lambda item: item.distance_from_origin_km,
                        )
                        if stop.distance_from_origin_km > session.distance_km
                    ), session.plan.charging_stops[0])
                    session.unavailable_station_ids.append(station.station_id)
                    self._emit(session, "STATION_UNAVAILABLE", f"Trạm {station.name} không khả dụng (mô phỏng).", {
                        "station_id": station.station_id,
                        "station_name": station.name,
                        "station_distance_km": station.distance_from_origin_km,
                        "vehicle_distance_km": round(session.distance_km, 3),
                    }, telemetry_snapshot_id=telemetry_snapshot_id, occurred_at=recorded_at)
            elif trigger and session.scenario == "ROUTE_DEVIATION":
                distance_to_route_km = (
                    session.request.scenario_value
                    if session.request.scenario_value is not None
                    else self._thresholds.max_off_route_distance_km + 0.01
                )
                lat = _offset_lat(lat, distance_to_route_km)
                if self._evaluator.classify(
                    off_route_distance_km=distance_to_route_km
                ) == "ROUTE_DEVIATION":
                    self._emit(session, "ROUTE_DEVIATION", "Xe đã lệch khỏi tuyến dự kiến.", {
                        "off_route_distance_km": distance_to_route_km,
                        "threshold_km": self._thresholds.max_off_route_distance_km,
                    }, telemetry_snapshot_id=telemetry_snapshot_id, occurred_at=recorded_at)
            elif trigger and session.scenario == "SOC_UNDERPERFORMANCE":
                soc_deficit_percent = (
                    session.request.scenario_value
                    if session.request.scenario_value is not None
                    else self._thresholds.max_soc_drop_deviation_percent + 0.1
                )
                actual_soc = expected_soc - soc_deficit_percent
                if self._evaluator.classify(
                    soc_deficit_percent=soc_deficit_percent
                ) == "SOC_UNDERPERFORMANCE":
                    self._emit(session, "SOC_UNDERPERFORMANCE", "SOC thực tế thấp hơn mức dự kiến.", {
                        "soc_deficit_percent": soc_deficit_percent,
                        "threshold_percent": self._thresholds.max_soc_drop_deviation_percent,
                    }, telemetry_snapshot_id=telemetry_snapshot_id, occurred_at=recorded_at)
            elif trigger and session.scenario == "STALE_TELEMETRY":
                age_seconds = (
                    session.request.scenario_value
                    if session.request.scenario_value is not None
                    else self._thresholds.max_telemetry_silent_seconds + 1
                )
                recorded_at -= timedelta(seconds=age_seconds)
                if self._evaluator.classify(silent_seconds=age_seconds) == "STALE_TELEMETRY":
                    freshness = "STALE"
                    self._emit(session, "STALE_TELEMETRY", "Không nhận được telemetry mới quá 60 giây.", {
                        "silent_seconds": age_seconds,
                        "threshold_seconds": self._thresholds.max_telemetry_silent_seconds,
                    }, telemetry_snapshot_id=telemetry_snapshot_id, occurred_at=recorded_at)

            session.telemetry = TelemetrySnapshot(
                snapshot_id=telemetry_snapshot_id,
                lat=lat, lon=lon, soc_percent=max(0, actual_soc),
                # Simulation acceleration must not be presented as the physical speed of the car.
                expected_soc_percent=max(0, expected_soc), speed_kph=60.0,
                distance_km=session.distance_km, progress_percent=progress * 100,
                distance_to_route_km=distance_to_route_km,
                freshness=freshness, recorded_at=recorded_at, age_seconds=age_seconds,
            )
            session.soc_risk = self._soc_risk_evaluator.observe(
                actual_soc_percent=max(0, actual_soc),
                expected_soc_percent=max(0, expected_soc),
                prior=session.soc_risk,
            )
            if progress >= 1 and session.status == "RUNNING":
                session.status = "COMPLETED"
            return self._state(session)

    def get_state(self, trip_id: str, owner_id: str) -> SimulationState:
        self._owned_trip(trip_id, owner_id)
        with self._lock:
            return self._state(self._require_session(trip_id))

    def pause(self, trip_id: str, owner_id: str) -> SimulationState:
        self._owned_trip(trip_id, owner_id)
        with self._lock:
            session = self._require_session(trip_id)
            if session.status == "RUNNING":
                session.status = "PAUSED"
            return self._state(session)

    def resume(self, trip_id: str, owner_id: str) -> SimulationState:
        self._owned_trip(trip_id, owner_id)
        with self._lock:
            session = self._require_session(trip_id)
            if session.status == "PAUSED":
                session.status = "RUNNING"
            return self._state(session)

    def reset(self, trip_id: str, owner_id: str) -> SimulationState:
        self._owned_trip(trip_id, owner_id)
        with self._lock:
            session = self._require_session(trip_id)
            session.status = "RUNNING"
            session.tick_count = 0
            session.distance_km = 0.0
            session.telemetry = None
            session.events.clear()
            session.unavailable_station_ids.clear()
            session.replan_required = False
            session.anomaly_emitted = False
            session.soc_risk = SOCRiskState.empty()
            return self._state(session)

    def refresh_telemetry(self, trip_id: str, owner_id: str) -> SimulationState:
        self._owned_trip(trip_id, owner_id)
        with self._lock:
            session = self._require_session(trip_id)
            latest_stale_event = next((
                event for event in reversed(session.events)
                if event.event_type == "STALE_TELEMETRY" and event.status == "ACTIVE"
            ), None)
            if session.status != "AWAITING_DECISION" or latest_stale_event is None:
                raise AppError(
                    "TELEMETRY_REFRESH_NOT_REQUIRED", 409,
                    "Hành trình hiện không chờ cập nhật GPS và mức pin.",
                )
            if session.telemetry is None:
                raise AppError("TELEMETRY_REQUIRED", 409, "Chưa có telemetry để làm mới.")

            latest_stale_event.status = "RESOLVED"
            resolve_event = getattr(self._repository, "resolve_monitoring_event", None)
            if callable(resolve_event):
                resolve_event(latest_stale_event.event_id)

            session.telemetry = session.telemetry.model_copy(update={
                "snapshot_id": str(uuid4()),
                "freshness": "FRESH",
                "recorded_at": datetime.now(UTC),
                "age_seconds": 0.0,
                "speed_kph": 0.0,
            })
            session.status = "RUNNING"
            session.replan_required = False
            return self._state(session)

    def activate_replanned_plan(
        self, trip_id: str, owner_id: str, request: SimulatorStartRequest
    ) -> SimulationState:
        self._owned_trip(trip_id, owner_id)
        if request.plan is None or not request.plan_id:
            raise AppError("PLAN_REQUIRED", 409, "Cần đầy đủ hành trình mới để tiếp tục mô phỏng.")
        records = self._repository.get_plan_versions(trip_id)
        record = next((item for item in records if item.id == request.plan_id), None)
        if record is None or record.status != "CONFIRMED":
            raise AppError(
                "PLAN_NOT_CONFIRMED", 409,
                "Chỉ có thể chuyển xe sang hành trình mới đã được xác nhận.",
            )
        plan = request.plan
        if plan.trip_id != trip_id or plan.plan_id != request.plan_id or plan.version != record.version:
            raise AppError("PLAN_MISMATCH", 409, "Hành trình mới không khớp phiên bản đã xác nhận.")
        if len(plan.route.polyline) < 2:
            raise AppError("ROUTE_REQUIRED", 409, "Hành trình mới chưa có polyline hợp lệ.")

        with self._lock:
            session = self._require_session(trip_id)
            if session.telemetry is None:
                raise AppError("TELEMETRY_REQUIRED", 409, "Không có vị trí hiện tại để nối hành trình mới.")
            route_start = plan.route.polyline[0]
            origin_gap_km = haversine_km(
                (session.telemetry.lat, session.telemetry.lon),
                (float(route_start[0]), float(route_start[1])),
            )
            if origin_gap_km > 2.0:
                raise AppError(
                    "REPLAN_ORIGIN_MISMATCH", 409,
                    "Hành trình mới không bắt đầu từ vị trí xe tại thời điểm xảy ra sự cố.",
                    {"origin_gap_km": round(origin_gap_km, 3)},
                )

            for event in session.events:
                if event.status != "ACTIVE":
                    continue
                event.status = "RESOLVED"
                resolve_event = getattr(self._repository, "resolve_monitoring_event", None)
                if callable(resolve_event):
                    resolve_event(event.event_id)

            previous_telemetry = session.telemetry
            speed_multiplier, estimated_seconds = self._simulation_pacing(
                plan.route.distance_km, request.speed_multiplier
            )
            session.plan = plan
            session.request = request
            session.scenario = "NORMAL"
            session.status = "RUNNING"
            session.distance_km = 0.0
            session.replan_required = False
            session.anomaly_emitted = False
            session.speed_multiplier = speed_multiplier
            session.estimated_duration_seconds = estimated_seconds
            session.soc_risk = SOCRiskState.empty()
            session.telemetry = previous_telemetry.model_copy(update={
                "snapshot_id": str(uuid4()),
                "lat": previous_telemetry.lat,
                "lon": previous_telemetry.lon,
                "soc_percent": previous_telemetry.soc_percent,
                "expected_soc_percent": previous_telemetry.soc_percent,
                "speed_kph": 0.0,
                "distance_km": 0.0,
                "progress_percent": 0.0,
                "freshness": "FRESH",
                "recorded_at": datetime.now(UTC),
                "age_seconds": 0.0,
            })
            return self._state(session)

    def decide(self, trip_id: str, owner_id: str, request: SimulationDecisionRequest) -> SimulationState:
        self._owned_trip(trip_id, owner_id)
        with self._lock:
            session = self._require_session(trip_id)
            if request.decision == "STOP":
                session.status = "STOPPED"
            elif request.decision == "CONTINUE":
                session.status = "RUNNING"
                session.replan_required = False
            else:
                # F3 hands this flag to F4. The planning agent is deliberately not invoked here.
                session.status = "STOPPED"
                session.replan_required = True
            return self._state(session)

    def _emit(
        self, session: _Session, event_type: str, message: str, payload: dict, *,
        telemetry_snapshot_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> None:
        session.anomaly_emitted = True
        session.status = "AWAITING_DECISION"
        session.replan_required = event_type != "STALE_TELEMETRY"
        event_id = str(uuid4())
        event_time = occurred_at or datetime.now(UTC)
        event = MonitoringEvent(
            id=event_id, trip_id=session.trip_id, event_type=event_type,
            telemetry_snapshot_id=telemetry_snapshot_id,
            source_sequence=len(session.events) + 1,
            related_plan_version=getattr(session.plan, "version", 0),
            severity="CRITICAL" if event_type in {"ROUTE_DEVIATION", "SOC_UNDERPERFORMANCE"} else "WARNING",
            message=message, payload=payload, created_at=event_time,
            correlation_id=telemetry_snapshot_id or event_id,
            tick=getattr(session, "tick_count", 0),
        )
        session.events.append(event)
        save_event = getattr(self._repository, "save_monitoring_event", None)
        if callable(save_event):
            save_event(event)

    @staticmethod
    def _point_at(polyline: list[list[float]], progress: float) -> tuple[float, float]:
        lat, lon, _ = point_along_polyline(polyline, progress)
        return lat, lon

    @staticmethod
    def _expected_soc(plan: PlanProposal, distance_km: float) -> float:
        # SOC is piecewise: it falls while driving, jumps only at a charging
        # stop (ARRIVAL -> DEPARTURE at the same distance), then falls again.
        # A single interpolation from origin to destination incorrectly turns
        # a mid-trip charge into gradual battery gain while the car is moving.
        points = [point.model_dump(mode="json") for point in plan.soc_points]
        initial_soc = plan.soc_points[0].soc_percent if plan.soc_points else 100.0
        return expected_soc_at_distance(
            points,
            distance_km,
            initial_soc_percent=initial_soc,
            final_soc_percent=plan.final_arrival_soc_percent,
            route_distance_km=plan.route.distance_km,
        )

    @staticmethod
    def _station_warning_before_move(
        plan: PlanProposal, *, current_distance_km: float, next_step_km: float
    ):
        route_distance = max(plan.route.distance_km, 0.01)
        warning_lead_km = min(20.0, max(5.0, route_distance * 0.15))
        upcoming = sorted(
            (
                stop for stop in plan.charging_stops
                if stop.distance_from_origin_km > current_distance_km
            ),
            key=lambda stop: stop.distance_from_origin_km,
        )
        if not upcoming:
            return None
        station = upcoming[0]
        lookahead_km = max(warning_lead_km, next_step_km)
        return station if current_distance_km + lookahead_km >= station.distance_from_origin_km else None

    @staticmethod
    def _random_scenarios(has_charging_stops: bool) -> list[str]:
        scenarios = ["NORMAL", "ROUTE_DEVIATION", "SOC_UNDERPERFORMANCE", "STALE_TELEMETRY"]
        if has_charging_stops:
            scenarios.append("STATION_UNAVAILABLE")
        return scenarios

    @staticmethod
    def _simulation_pacing(distance_km: float, requested_multiplier: float | None) -> tuple[float, int]:
        """Target ~1 minute for short trips and up to ~5 minutes for very long trips."""
        distance = max(0.01, distance_km)
        if requested_multiplier is not None:
            multiplier = requested_multiplier
        else:
            target_seconds = min(300.0, 60.0 + 6.0 * math.sqrt(distance))
            multiplier = min(100.0, max(0.1, distance / (0.06 * target_seconds)))
        estimated = max(1, round(distance / (0.06 * multiplier)))
        return round(multiplier, 2), estimated

    def _owned_trip(self, trip_id: str, owner_id: str):
        trip = self._repository.get_trip(trip_id)
        if trip is None:
            raise NotFoundError("Trip")
        if trip.owner_id != owner_id:
            raise ForbiddenError()
        return trip

    def _require_session(self, trip_id: str) -> _Session:
        session = self._sessions.get(trip_id)
        if session is None:
            raise AppError("SIMULATION_NOT_STARTED", 409, "Mô phỏng chưa được bắt đầu.")
        return session

    @staticmethod
    def _state(session: _Session) -> SimulationState:
        return SimulationState(
            trip_id=session.trip_id, plan_id=session.plan.plan_id, status=session.status,
            selected_scenario=session.scenario, telemetry=session.telemetry, events=session.events,
            unavailable_station_ids=session.unavailable_station_ids,
            replan_required=session.replan_required, agent_invocation_count=0,
            tick_count=session.tick_count,
            speed_multiplier=session.speed_multiplier,
            estimated_duration_seconds=session.estimated_duration_seconds,
            soc_risk=session.soc_risk,
        )
