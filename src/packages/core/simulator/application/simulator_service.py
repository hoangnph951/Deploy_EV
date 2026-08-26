from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import RLock
from uuid import uuid4

from src.packages.agent.replanning.supervisor import ReplanningSupervisor
from src.packages.contracts.monitoring import MonitoringEvent, TelemetrySnapshot
from src.packages.contracts.replanning import AgentDecision, CandidatePlanSummary, PlanDiff
from src.packages.contracts.simulator import (
    SimulationChargingStation,
    SimulationRunResponse,
    SimulationStartRequest,
)
from src.packages.contracts.trips import AssumptionSnapshot, DataProvenance, PlanProposal
from src.packages.core.monitoring.application.monitoring_service import MonitoringService
from src.packages.core.monitoring.domain.geometry import (
    distance_to_polyline_km,
    offset_perpendicular,
    point_along_polyline,
)
from src.packages.core.monitoring.domain.soc import expected_soc_at_distance
from src.packages.core.simulator.application.catalog_service import SimulationCatalogService
from src.packages.core.trips.domain.entities import VehicleProfile
from src.packages.core.trips.infrastructure.environment import EnvironmentProviderError
from src.packages.core.trips.infrastructure.routing import RoutingProviderError
from src.packages.core.trips.infrastructure.station_service import CandidateStation, StationProviderError


@dataclass
class _Run:
    run_id: str
    owner_id: str
    case_id: str
    status: str
    current_tick: int
    total_ticks: int
    speed_multiplier: int
    started_at: datetime
    updated_at: datetime
    telemetry: TelemetrySnapshot | None = None
    events: list[MonitoringEvent] = field(default_factory=list)
    decisions: list[AgentDecision] = field(default_factory=list)
    emitted_types: set[str] = field(default_factory=set)
    route_polyline: list[list[float]] = field(default_factory=list)
    route_start_tick: int = 0
    incident_resolved: bool = False
    applied_action: str | None = None
    telemetry_history: list[tuple[float, float]] = field(default_factory=list)
    replanned_plan: PlanProposal | None = None


class SimulatorService:
    def __init__(
        self,
        catalog: SimulationCatalogService,
        monitoring: MonitoringService | None = None,
        supervisor: ReplanningSupervisor | None = None,
    ):
        self.catalog = catalog
        self._monitoring = monitoring or MonitoringService()
        self._supervisor = supervisor or ReplanningSupervisor()
        self._runs: dict[str, _Run] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._lock = RLock()

    def start(self, owner_id: str, request: SimulationStartRequest) -> SimulationRunResponse:
        case = self.catalog.get_case(request.case_id)
        if case.readiness != "READY":
            raise ValueError(case.readiness_reason or "Simulation case is not ready.")
        key = (owner_id, request.idempotency_key)
        with self._lock:
            existing = self._idempotency.get(key)
            if existing:
                return self._response(self._runs[existing])
            now = datetime.now(UTC)
            snapshot = self.catalog.get_snapshot_for_case(case.case_id)
            run = _Run(
                run_id=str(uuid4()),
                owner_id=owner_id,
                case_id=case.case_id,
                status="RUNNING",
                current_tick=-1,
                total_ticks=20,
                speed_multiplier=request.speed_multiplier,
                started_at=now,
                updated_at=now,
                route_polyline=[list(point) for point in snapshot.route.get("polyline") or []],
            )
            self._runs[run.run_id] = run
            self._idempotency[key] = run.run_id
            return self._response(run)

    def get(self, owner_id: str, run_id: str) -> SimulationRunResponse:
        return self._response(self._owned_run(owner_id, run_id))

    def step(self, owner_id: str, run_id: str) -> SimulationRunResponse:
        with self._lock:
            run = self._owned_run(owner_id, run_id)
            if run.status != "RUNNING":
                return self._response(run)
            if run.current_tick + 1 >= run.total_ticks:
                run.status = "COMPLETED"
                run.updated_at = datetime.now(UTC)
                return self._response(run)
            run.current_tick += 1
            self._emit(run)
            if run.current_tick >= run.total_ticks - 1:
                run.status = "COMPLETED"
            run.updated_at = datetime.now(UTC)
            return self._response(run)

    def pause(self, owner_id: str, run_id: str) -> SimulationRunResponse:
        run = self._owned_run(owner_id, run_id)
        if run.status == "RUNNING":
            run.status = "PAUSED"
        run.updated_at = datetime.now(UTC)
        return self._response(run)

    def resume(self, owner_id: str, run_id: str) -> SimulationRunResponse:
        run = self._owned_run(owner_id, run_id)
        if run.status == "PAUSED":
            run.status = "RUNNING"
        run.updated_at = datetime.now(UTC)
        return self._response(run)

    def reset(self, owner_id: str, run_id: str) -> SimulationRunResponse:
        run = self._owned_run(owner_id, run_id)
        snapshot = self.catalog.get_snapshot_for_case(run.case_id)
        run.status = "RUNNING"
        run.current_tick = -1
        run.telemetry = None
        run.events.clear()
        run.decisions.clear()
        run.emitted_types.clear()
        run.route_polyline = [list(point) for point in snapshot.route.get("polyline") or []]
        run.route_start_tick = 0
        run.incident_resolved = False
        run.applied_action = None
        run.telemetry_history.clear()
        run.replanned_plan = None
        run.updated_at = datetime.now(UTC)
        return self._response(run)

    def refresh_telemetry(self, owner_id: str, run_id: str) -> SimulationRunResponse:
        """Accept the stale-data action and emit a fresh sample before resuming."""
        with self._lock:
            run = self._owned_run(owner_id, run_id)
            if run.status != "AWAITING_ACTION" or not run.decisions or run.telemetry is None:
                raise ValueError("Simulation run is not waiting for fresh telemetry.")
            if run.decisions[-1].action != "REQUEST_NEW_TELEMETRY":
                raise ValueError("Simulation run does not require fresh telemetry.")
            run.incident_resolved = True
            run.status = "RUNNING"
            run.updated_at = datetime.now(UTC)
            return self.step(owner_id, run_id)

    def replan(self, owner_id: str, run_id: str) -> SimulationRunResponse:
        """Apply the already guarded F4 proposal only after explicit user action."""
        with self._lock:
            run = self._owned_run(owner_id, run_id)
            if run.status != "AWAITING_ACTION" or not run.decisions or run.telemetry is None:
                raise ValueError("Simulation run is not waiting for a replanning decision.")
            decision = run.decisions[-1]
            snapshot = self.catalog.get_snapshot_for_case(run.case_id)
            if decision.action != "REQUEST_NEW_TELEMETRY":
                from src.packages.agent.planning.graph import planning_agent

                vehicle_profile = VehicleProfile(**snapshot.input_state["vehicle_profile"])
                assumptions = AssumptionSnapshot.model_validate(snapshot.input_state["assumptions"])
                excluded_station_ids = [
                    event.station_id for event in run.events if event.station_id
                ]
                blacklisted = set(excluded_station_ids)
                traveled_distance = (
                    float(snapshot.route.get("distance_km") or 0)
                    * run.telemetry.progress_percent
                    / 100
                )
                seed_candidate_stations: list[CandidateStation] = []
                for stop in snapshot.charging_stops:
                    station_id = str(stop.get("station_id") or "")
                    station_distance = float(stop.get("distance_from_origin_km") or 0)
                    if not station_id or station_id in blacklisted or station_distance <= traveled_distance:
                        continue
                    provenance = (
                        DataProvenance.model_validate(stop["provenance"])
                        if stop.get("provenance")
                        else None
                    )
                    connector = str(stop.get("connector_type") or stop.get("connector_standard") or "CCS2")
                    seed_candidate_stations.append(
                        CandidateStation(
                            station_id=station_id,
                            name=str(stop.get("name") or "Trạm sạc"),
                            lat=float(stop["lat"]),
                            lon=float(stop.get("lon", stop.get("lng"))),
                            address=str(stop.get("address") or ""),
                            connector_types=[connector],
                            connector_standard=str(stop.get("connector_standard") or connector),
                            max_power_kw=float(stop.get("max_power_kw") or 1),
                            port_count=int(stop.get("port_count") or 1),
                            station_status=str(stop.get("station_status") or "ACTIVE"),
                            opening_24_7=stop.get("opening_24_7"),
                            access_type=str(stop.get("access_type") or "Public"),
                            parking_fee=stop.get("parking_fee"),
                            station_updated_at=stop.get("station_updated_at"),
                            detour_distance_km=float(stop.get("detour_distance_km") or 0),
                            detour_duration_min=float(stop.get("detour_duration_min") or 0),
                            freshness="STALE" if stop.get("freshness") == "STALE" else "FRESH",
                            distance_from_origin_km=max(0.0, station_distance - traveled_distance),
                            provenance=provenance,
                        )
                    )
                try:
                    state = planning_agent.invoke(
                        {
                            "trip_id": f"simulation:{run.run_id}",
                            "owner_id": owner_id,
                            "origin_name": "Vị trí hiện tại của xe",
                            "origin_lat": run.telemetry.lat,
                            "origin_lng": run.telemetry.lng,
                            "destination_name": snapshot.destination_name,
                            "destination_lat": snapshot.destination_lat,
                            "destination_lng": snapshot.destination_lng,
                            "initial_soc_percent": run.telemetry.actual_soc_percent,
                            "vehicle_profile": vehicle_profile,
                            "assumptions": assumptions,
                            "excluded_station_ids": excluded_station_ids,
                            "seed_candidate_stations": seed_candidate_stations,
                            "metadata": {
                                "trigger": "F4_REPLAN",
                                "monitoring_event_ids": [event.event_id for event in run.events],
                            },
                        }
                    )
                except (RoutingProviderError, StationProviderError, EnvironmentProviderError) as exc:
                    raise ValueError(f"F1 realtime provider thất bại: {exc}") from exc
                candidate = state.get("plan_proposal")
                if candidate is None:
                    outcome = state.get("no_feasible_plan")
                    summary = getattr(outcome, "summary", None) or "F1 không tạo được candidate plan an toàn."
                    raise ValueError(summary)
                if any(stop.station_id in blacklisted for stop in candidate.charging_stops):
                    raise ValueError("F1 candidate vi phạm blacklist trạm không khả dụng.")
                candidate.trigger_reason = "F4_REPLAN"
                run.replanned_plan = candidate
                run.route_polyline = [list(point) for point in candidate.route.polyline]
                run.route_start_tick = run.current_tick
                old_station_ids = [
                    str(stop.get("station_id"))
                    for stop in snapshot.charging_stops
                    if stop.get("station_id")
                ]
                candidate_station_ids = [stop.station_id for stop in candidate.charging_stops]
                remaining_ratio = max(0.0, 1.0 - run.telemetry.progress_percent / 100)
                old_remaining_distance = float(snapshot.route.get("distance_km") or 0) * remaining_ratio
                old_remaining_duration = float(snapshot.route.get("duration_min") or 0) * remaining_ratio
                decision.candidate_plan = CandidatePlanSummary(
                    candidate_id=candidate.plan_id,
                    origin_lat=run.telemetry.lat,
                    origin_lng=run.telemetry.lng,
                    destination_lat=snapshot.destination_lat,
                    destination_lng=snapshot.destination_lng,
                    distance_km=candidate.route.distance_km,
                    duration_min=candidate.route.duration_min,
                    final_soc_percent=candidate.final_arrival_soc_percent,
                    station_ids=candidate_station_ids,
                    safety_verdict="FEASIBLE",
                    simulation_only=False,
                )
                decision.plan_diff = PlanDiff(
                    distance_delta_km=round(candidate.route.distance_km - old_remaining_distance, 2),
                    duration_delta_min=round(candidate.route.duration_min - old_remaining_duration, 2),
                    final_soc_delta_percent=round(
                        candidate.final_arrival_soc_percent
                        - float(snapshot.energy.get("final_arrival_soc_percent") or 0),
                        2,
                    ),
                    removed_station_ids=excluded_station_ids,
                    added_station_ids=[
                        station_id for station_id in candidate_station_ids
                        if station_id not in old_station_ids
                    ],
                    old_safety="DEGRADED",
                    candidate_safety="FEASIBLE",
                    summary=(
                        f"F1 realtime trả plan {candidate.route.distance_km:.1f} km, "
                        f"{len(candidate_station_ids)} trạm và SOC đích "
                        f"{candidate.final_arrival_soc_percent:.1f}%."
                    ),
                )
                decision.explanation = (
                    "F1 realtime đã chạy từ GPS và SOC tại sự cố, áp blacklist trạm lỗi "
                    "và trả candidate đã qua energy cùng feasibility check."
                )

            run.incident_resolved = True
            run.applied_action = decision.action
            run.status = "RUNNING"
            run.updated_at = datetime.now(UTC)
            return self._response(run)

    def _emit(self, run: _Run) -> None:
        case = self.catalog.get_case(run.case_id)
        snapshot = self.catalog.get_snapshot_for_case(run.case_id)
        fraction = run.current_tick / max(1, run.total_ticks - 1)
        polyline = run.route_polyline or snapshot.route["polyline"]
        movement_fraction = (run.current_tick - run.route_start_tick) / max(
            1,
            run.total_ticks - 1 - run.route_start_tick,
        )
        lat, lng, route_progress_km = point_along_polyline(polyline, movement_fraction)
        trigger = run.current_tick >= 10 and not run.incident_resolved
        if case.profile == "ROUTE_DEVIATION" and trigger:
            lat, lng = offset_perpendicular(polyline, fraction, 2.05)

        route_distance_km = float(snapshot.route.get("distance_km") or route_progress_km)
        distance_km = route_distance_km * fraction
        expected_soc = expected_soc_at_distance(
            snapshot.energy.get("soc_points") or [],
            distance_km,
            initial_soc_percent=snapshot.initial_soc_percent,
            final_soc_percent=float(snapshot.energy.get("final_arrival_soc_percent") or snapshot.initial_soc_percent),
            route_distance_km=route_distance_km,
        )
        actual_soc = max(0.0, expected_soc - (0.4 if run.current_tick % 2 else 0.2))
        if case.profile == "SOC_UNDERPERFORMANCE" and trigger:
            actual_soc = max(0.0, expected_soc - 5.1)
        elif case.profile == "NO_FEASIBLE_ALTERNATIVE" and trigger:
            actual_soc = max(0.0, expected_soc - 8.0)

        now = datetime.now(UTC)
        age = 61.0 if case.profile == "STALE_TELEMETRY" and trigger else 0.0
        recorded_at = now - timedelta(seconds=age)
        telemetry = TelemetrySnapshot(
            event_id=f"{run.run_id}:tick:{run.current_tick}",
            trip_id=f"log:{snapshot.run_id}",
            lat=lat,
            lng=lng,
            actual_soc_percent=round(actual_soc, 2),
            expected_soc_percent=round(expected_soc, 2),
            progress_percent=round(fraction * 100, 2),
            distance_to_route_km=round(distance_to_polyline_km(lat, lng, polyline), 3),
            scenario_id=case.case_id,
            simulation_run_id=run.run_id,
            tick=run.current_tick,
            recorded_at=recorded_at,
            age_seconds=age,
        )
        station_id = None
        if case.profile in {"STATION_UNAVAILABLE", "NO_FEASIBLE_ALTERNATIVE"} and not run.incident_resolved:
            stops = sorted(
                snapshot.charging_stops,
                key=lambda stop: float(stop.get("distance_from_origin_km") or 0),
            )
            if stops:
                station_distance = float(stops[0].get("distance_from_origin_km") or 0)
                # Announce the disruption before arrival, never after the car
                # has already passed the affected charging stop.
                warning_distance_km = max(20.0, route_distance_km / max(run.total_ticks - 1, 1))
                before_station = station_distance - warning_distance_km
                if before_station <= distance_km < station_distance:
                    station_id = str(stops[0].get("station_id"))
        new_events = self._monitoring.evaluate(
            telemetry,
            profile=case.profile,
            station_id=station_id,
            already_emitted=run.emitted_types,
        )
        run.telemetry = telemetry
        run.telemetry_history.append((telemetry.lat, telemetry.lng))
        if new_events:
            run.events.extend(new_events)
            run.emitted_types.update(item.event_type for item in new_events)
            decision = self._supervisor.decide(
                snapshot=snapshot,
                telemetry=telemetry,
                events=new_events,
                profile=case.profile,
            )
            run.decisions.append(decision)
            run.status = "AWAITING_ACTION"

    def _owned_run(self, owner_id: str, run_id: str) -> _Run:
        try:
            run = self._runs[run_id]
        except KeyError as exc:
            raise KeyError("Simulation run not found.") from exc
        if run.owner_id != owner_id:
            raise PermissionError("Simulation run belongs to another user.")
        return run

    def _response(self, run: _Run) -> SimulationRunResponse:
        snapshot = self.catalog.get_snapshot_for_case(run.case_id)
        raw_stations = list(snapshot.charging_stops)
        if run.replanned_plan is not None:
            raw_stations.extend(stop.model_dump(mode="json") for stop in run.replanned_plan.charging_stops)
        charging_stations_by_id: dict[str, SimulationChargingStation] = {}
        for stop in raw_stations:
            if stop.get("lat") is None or (stop.get("lon") is None and stop.get("lng") is None):
                continue
            station = SimulationChargingStation(
                station_id=str(stop.get("station_id") or "unknown-station"),
                name=str(stop.get("name") or "Trạm sạc"),
                lat=float(stop["lat"]),
                lng=float(stop.get("lon", stop.get("lng"))),
                address=str(stop.get("address") or ""),
                arrival_soc_percent=stop.get("arrival_soc_percent"),
                departure_soc_percent=stop.get("departure_soc_percent"),
                charge_duration_min=stop.get("charge_duration_min"),
                max_power_kw=stop.get("max_power_kw"),
                connector_type=str(stop.get("connector_type") or ""),
                station_status=str(stop.get("station_status") or "UNKNOWN"),
            )
            charging_stations_by_id[station.station_id] = station
        return SimulationRunResponse(
            run_id=run.run_id,
            owner_id=run.owner_id,
            case=self.catalog.get_case(run.case_id),
            status=run.status,
            current_tick=max(0, run.current_tick),
            total_ticks=run.total_ticks,
            speed_multiplier=run.speed_multiplier,
            started_at=run.started_at,
            updated_at=run.updated_at,
            telemetry=run.telemetry,
            route_polyline=[tuple(point) for point in run.route_polyline],
            original_route_polyline=[tuple(point) for point in snapshot.route.get("polyline") or []],
            actual_path=list(run.telemetry_history),
            charging_stations=list(charging_stations_by_id.values()),
            monitoring_events=run.events,
            agent_decisions=run.decisions,
            requires_user_action=run.status == "AWAITING_ACTION",
            applied_action=run.applied_action,
            replanned_plan=run.replanned_plan,
        )
