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
from src.packages.core.trips.application.errors import AppError, ForbiddenError, NotFoundError


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(h))


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
        self._sessions: dict[str, _Session] = {}
        self._lock = RLock()

    def start(self, trip_id: str, owner_id: str, request: SimulatorStartRequest) -> SimulationState:
        trip = self._owned_trip(trip_id, owner_id)
        if request.plan is not None:
            plan = request.plan
            if plan.trip_id != trip_id or (request.plan_id and plan.plan_id != request.plan_id):
                raise AppError("PLAN_MISMATCH", 409, "Proposal đã chọn không thuộc chuyến đi này.")
        else:
            records = self._repository.get_plan_versions(trip_id)
            record = next((item for item in records if item.id == request.plan_id), None) if request.plan_id else None
            record = record or (records[-1] if records else None)
            if record is None or not record.proposal_json:
                raise AppError("PLAN_REQUIRED", 409, "Hãy lập kế hoạch trước khi bắt đầu mô phỏng.")
            import json
            plan = PlanProposal.model_validate(json.loads(record.proposal_json))
        if len(plan.route.polyline) < 2:
            raise AppError("ROUTE_REQUIRED", 409, "Kế hoạch chưa có polyline để mô phỏng.")
        if request.scenario == "STATION_UNAVAILABLE" and not plan.charging_stops:
            raise AppError(
                "STATION_REQUIRED", 409,
                "Kịch bản STATION_UNAVAILABLE cần một proposal có ít nhất một trạm sạc.",
            )
        scenario = request.scenario
        if scenario == "RANDOM":
            rng = random.Random(request.seed)
            if rng.random() >= request.unhappy_probability:
                scenario = "NORMAL"
            else:
                candidates = ["ROUTE_DEVIATION", "SOC_UNDERPERFORMANCE", "STALE_TELEMETRY"]
                if plan.charging_stops:
                    candidates.append("STATION_UNAVAILABLE")
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
            session.distance_km = min(route_distance, session.distance_km + step_km)
            progress = session.distance_km / route_distance
            lat, lon = self._point_at(session.plan.route.polyline, progress)
            expected_soc = self._expected_soc(session.plan, progress)
            actual_soc = expected_soc
            freshness = "FRESH"
            recorded_at = datetime.now(UTC)
            trigger = progress >= 0.35 and not session.anomaly_emitted

            if trigger and session.scenario == "ROUTE_DEVIATION":
                # Strictly over 2 km: 2.01 triggers while 1.99 does not.
                lat = _offset_lat(lat, self._thresholds.max_off_route_distance_km + 0.01)
                self._emit(session, "ROUTE_DEVIATION", "Xe đã lệch khỏi tuyến dự kiến.", {
                    "off_route_distance_km": self._thresholds.max_off_route_distance_km + 0.01,
                    "threshold_km": self._thresholds.max_off_route_distance_km,
                })
            elif trigger and session.scenario == "SOC_UNDERPERFORMANCE":
                actual_soc = expected_soc - self._thresholds.max_soc_drop_deviation_percent - 0.1
                self._emit(session, "SOC_UNDERPERFORMANCE", "SOC thực tế thấp hơn mức dự kiến.", {
                    "soc_deficit_percent": self._thresholds.max_soc_drop_deviation_percent + 0.1,
                    "threshold_percent": self._thresholds.max_soc_drop_deviation_percent,
                })
            elif trigger and session.scenario == "STATION_UNAVAILABLE" and session.plan.charging_stops:
                station = session.plan.charging_stops[0]
                session.unavailable_station_ids.append(station.station_id)
                self._emit(session, "STATION_UNAVAILABLE", f"Trạm {station.name} không khả dụng (mô phỏng).", {
                    "station_id": station.station_id, "station_name": station.name,
                })
            elif trigger and session.scenario == "STALE_TELEMETRY":
                recorded_at -= timedelta(seconds=self._thresholds.max_telemetry_silent_seconds + 1)
                freshness = "STALE"
                self._emit(session, "STALE_TELEMETRY", "Không nhận được telemetry mới quá 60 giây.", {
                    "silent_seconds": self._thresholds.max_telemetry_silent_seconds + 1,
                    "threshold_seconds": self._thresholds.max_telemetry_silent_seconds,
                })

            session.telemetry = TelemetrySnapshot(
                lat=lat, lon=lon, soc_percent=max(0, actual_soc),
                # Simulation acceleration must not be presented as the physical speed of the car.
                expected_soc_percent=max(0, expected_soc), speed_kph=60.0,
                distance_km=session.distance_km, progress_percent=progress * 100,
                freshness=freshness, recorded_at=recorded_at,
            )
            if progress >= 1 and session.status == "RUNNING":
                session.status = "COMPLETED"
            return self._state(session)

    def get_state(self, trip_id: str, owner_id: str) -> SimulationState:
        self._owned_trip(trip_id, owner_id)
        with self._lock:
            return self._state(self._require_session(trip_id))

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

    def _emit(self, session: _Session, event_type: str, message: str, payload: dict) -> None:
        session.anomaly_emitted = True
        session.status = "AWAITING_DECISION"
        session.replan_required = event_type != "STALE_TELEMETRY"
        session.events.append(MonitoringEvent(
            id=str(uuid4()), trip_id=session.trip_id, event_type=event_type,
            severity="CRITICAL" if event_type in {"ROUTE_DEVIATION", "SOC_UNDERPERFORMANCE"} else "WARNING",
            message=message, payload=payload, created_at=datetime.now(UTC),
        ))

    @staticmethod
    def _point_at(polyline: list[list[float]], progress: float) -> tuple[float, float]:
        index = min(len(polyline) - 2, int(progress * (len(polyline) - 1)))
        local = progress * (len(polyline) - 1) - index
        a, b = polyline[index], polyline[index + 1]
        return a[0] + (b[0] - a[0]) * local, a[1] + (b[1] - a[1]) * local

    @staticmethod
    def _expected_soc(plan: PlanProposal, progress: float) -> float:
        if not plan.soc_points:
            return 100 - progress * 20
        start = plan.soc_points[0].soc_percent
        end = plan.final_arrival_soc_percent
        return start + (end - start) * progress

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
        )
