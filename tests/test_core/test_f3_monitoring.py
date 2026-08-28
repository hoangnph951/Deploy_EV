from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from src.packages.contracts.monitoring import (
    MonitoringThresholds,
    SimulatorStartRequest,
    TelemetrySnapshot,
)
from src.packages.contracts.trips import PlanProposal
from src.packages.core.monitoring.application.service import MonitoringEvaluator, MonitoringSimulatorService
from src.packages.core.monitoring.domain.risk import SOCRiskState


class EventRepository:
    def __init__(self):
        self.events = {}
        self.resolved_event_ids = []
        self.plan_versions = []

    def save_monitoring_event(self, event):
        self.events[event.event_id] = event

    def resolve_monitoring_event(self, event_id):
        self.resolved_event_ids.append(event_id)
        return True

    def get_trip(self, trip_id):
        return SimpleNamespace(id=trip_id, owner_id="owner-1")

    def get_plan_versions(self, trip_id):
        return self.plan_versions


def test_normal_has_zero_unnecessary_agent_trigger():
    evaluator = MonitoringEvaluator()
    assert evaluator.classify(off_route_distance_km=1.99, soc_deficit_percent=4.9, silent_seconds=59) == "NORMAL"


def test_thresholds_are_strictly_greater_than_proposal_values():
    evaluator = MonitoringEvaluator(MonitoringThresholds())
    assert evaluator.classify(off_route_distance_km=2.0) == "NORMAL"
    assert evaluator.classify(off_route_distance_km=2.01) == "ROUTE_DEVIATION"
    assert evaluator.classify(soc_deficit_percent=5.0) == "NORMAL"
    assert evaluator.classify(soc_deficit_percent=5.1) == "SOC_UNDERPERFORMANCE"
    assert evaluator.classify(silent_seconds=60) == "NORMAL"
    assert evaluator.classify(silent_seconds=61) == "STALE_TELEMETRY"


def test_station_unavailable_is_explicit_simulator_event():
    assert MonitoringEvaluator().classify(station_unavailable=True) == "STATION_UNAVAILABLE"


def test_simulation_pacing_scales_with_trip_distance():
    short_multiplier, short_seconds = MonitoringSimulatorService._simulation_pacing(10, None)
    long_multiplier, long_seconds = MonitoringSimulatorService._simulation_pacing(1000, None)
    assert long_multiplier > short_multiplier
    assert short_seconds < long_seconds <= 300
    assert short_seconds >= 60


def test_random_scenarios_are_equally_selectable_when_plan_has_charging_stops():
    scenarios = MonitoringSimulatorService._random_scenarios(has_charging_stops=True)

    assert scenarios == [
        "NORMAL",
        "ROUTE_DEVIATION",
        "SOC_UNDERPERFORMANCE",
        "STALE_TELEMETRY",
        "STATION_UNAVAILABLE",
    ]


def test_random_scenarios_exclude_station_event_when_plan_has_no_charging_stops():
    scenarios = MonitoringSimulatorService._random_scenarios(has_charging_stops=False)

    assert scenarios == [
        "NORMAL",
        "ROUTE_DEVIATION",
        "SOC_UNDERPERFORMANCE",
        "STALE_TELEMETRY",
    ]


def test_f3_persists_emitted_event_at_the_boundary():
    repository = EventRepository()
    service = MonitoringSimulatorService(repository)
    session = type("Session", (), {
        "trip_id": "trip-1",
        "plan": type("Plan", (), {"version": 3})(),
        "anomaly_emitted": False,
        "status": "RUNNING",
        "replan_required": False,
        "events": [],
    })()

    service._emit(session, "ROUTE_DEVIATION", "off route", {"off_route_distance_km": 2.1})

    assert len(session.events) == 1
    assert repository.events[session.events[0].event_id].trip_id == "trip-1"
    assert session.events[0].related_plan_version == 3


def test_random_demo_uses_fifty_percent_event_probability_by_default():
    request = SimulatorStartRequest(plan_id="plan-1", seed=9, scenario="RANDOM")

    assert request.unhappy_probability == 0.5


def test_expected_soc_decreases_while_driving_and_only_jumps_at_charger():
    def point(distance_km, soc_percent, kind):
        return SimpleNamespace(
            distance_km=distance_km,
            soc_percent=soc_percent,
            kind=kind,
            model_dump=lambda mode: {
                "distance_km": distance_km,
                "soc_percent": soc_percent,
                "kind": kind,
            },
        )

    plan = SimpleNamespace(
        route=SimpleNamespace(distance_km=100.0),
        final_arrival_soc_percent=20.0,
        soc_points=[
            point(0.0, 80.0, "ORIGIN"),
            point(40.0, 20.0, "ARRIVAL"),
            point(40.0, 80.0, "DEPARTURE"),
            point(100.0, 20.0, "DESTINATION"),
        ],
    )

    assert MonitoringSimulatorService._expected_soc(plan, 20.0) == pytest.approx(50.0)
    assert MonitoringSimulatorService._expected_soc(plan, 39.0) == pytest.approx(21.5)
    assert MonitoringSimulatorService._expected_soc(plan, 40.0) == pytest.approx(20.0)
    assert MonitoringSimulatorService._expected_soc(plan, 40.001) > 79.0
    assert MonitoringSimulatorService._expected_soc(plan, 70.0) == pytest.approx(50.0)


def test_station_unavailable_warning_is_raised_before_next_step_can_pass_station():
    station = SimpleNamespace(distance_from_origin_km=60.0)
    plan = SimpleNamespace(
        route=SimpleNamespace(distance_km=100.0),
        charging_stops=[station],
    )

    assert MonitoringSimulatorService._station_warning_before_move(
        plan, current_distance_km=44.0, next_step_km=1.0,
    ) is None
    assert MonitoringSimulatorService._station_warning_before_move(
        plan, current_distance_km=45.0, next_step_km=1.0,
    ) is station
    assert MonitoringSimulatorService._station_warning_before_move(
        plan, current_distance_km=50.0, next_step_km=11.0,
    ) is station
    assert MonitoringSimulatorService._station_warning_before_move(
        plan, current_distance_km=61.0, next_step_km=1.0,
    ) is None


def test_vehicle_position_uses_travelled_distance_not_polyline_vertex_count():
    # The first segment is only 10% of the route. Index-based interpolation
    # incorrectly placed 50% progress at lng=0.01 (the second vertex).
    lat, lon = MonitoringSimulatorService._point_at(
        [[0.0, 0.0], [0.0, 0.01], [0.0, 0.1]],
        0.5,
    )

    assert lat == pytest.approx(0.0)
    assert lon == pytest.approx(0.05, abs=0.001)


def test_refreshing_stale_telemetry_resolves_event_and_resumes_current_plan():
    repository = EventRepository()
    service = MonitoringSimulatorService(repository)
    stale_time = datetime.now(UTC) - timedelta(seconds=61)
    session = SimpleNamespace(
        trip_id="trip-1",
        plan=SimpleNamespace(plan_id="plan-1", version=1),
        scenario="STALE_TELEMETRY",
        status="RUNNING",
        tick_count=5,
        telemetry=TelemetrySnapshot(
            lat=21.0, lon=105.0, soc_percent=42.0, expected_soc_percent=42.0,
            speed_kph=60.0, distance_km=12.0, progress_percent=20.0,
            freshness="STALE", recorded_at=stale_time, age_seconds=61.0,
        ),
        events=[],
        unavailable_station_ids=[],
        replan_required=False,
        anomaly_emitted=False,
        speed_multiplier=1.0,
        estimated_duration_seconds=60,
        soc_risk=SOCRiskState.empty(),
    )
    service._emit(session, "STALE_TELEMETRY", "stale", {"silent_seconds": 61})
    service._sessions[session.trip_id] = session

    refreshed = service.refresh_telemetry("trip-1", "owner-1")

    assert refreshed.status == "RUNNING"
    assert refreshed.telemetry.freshness == "FRESH"
    assert refreshed.telemetry.age_seconds == 0
    assert refreshed.telemetry.snapshot_id
    assert refreshed.events[-1].status == "RESOLVED"
    assert repository.resolved_event_ids == [refreshed.events[-1].event_id]


def test_activating_replan_keeps_vehicle_at_incident_position_instead_of_restarting_trip():
    repository = EventRepository()
    repository.plan_versions = [
        SimpleNamespace(id="plan-2", version=2, status="CONFIRMED"),
    ]
    service = MonitoringSimulatorService(repository)
    current_position = (21.0123, 105.0456)
    candidate = PlanProposal.model_construct(
        plan_id="plan-2",
        trip_id="trip-1",
        version=2,
        status="CONFIRMED",
        route=SimpleNamespace(
            distance_km=45.0,
            polyline=[list(current_position), [20.9, 105.3]],
        ),
        soc_points=[],
        final_arrival_soc_percent=18.0,
        charging_stops=[],
    )
    old_request = SimulatorStartRequest(plan_id="plan-1", scenario="STATION_UNAVAILABLE")
    session = SimpleNamespace(
        trip_id="trip-1",
        plan=SimpleNamespace(plan_id="plan-1", version=1),
        request=old_request,
        scenario="STATION_UNAVAILABLE",
        status="RUNNING",
        tick_count=17,
        distance_km=32.0,
        telemetry=TelemetrySnapshot(
            lat=current_position[0], lon=current_position[1],
            soc_percent=31.5, expected_soc_percent=33.0,
            speed_kph=60.0, distance_km=32.0, progress_percent=42.0,
            freshness="FRESH", recorded_at=datetime.now(UTC),
        ),
        events=[],
        unavailable_station_ids=["ST-FAILED"],
        replan_required=False,
        anomaly_emitted=False,
        speed_multiplier=1.0,
        estimated_duration_seconds=60,
        soc_risk=SOCRiskState.empty(),
    )
    service._emit(
        session, "STATION_UNAVAILABLE", "station failed",
        {"station_id": "ST-FAILED"},
    )
    service._sessions[session.trip_id] = session

    activated = service.activate_replanned_plan(
        "trip-1",
        "owner-1",
        SimulatorStartRequest(plan_id="plan-2", plan=candidate, scenario="NORMAL"),
    )

    assert activated.plan_id == "plan-2"
    assert activated.status == "RUNNING"
    assert activated.tick_count == 17
    assert (activated.telemetry.lat, activated.telemetry.lon) == current_position
    assert activated.telemetry.soc_percent == 31.5
    assert activated.telemetry.progress_percent == 0.0
    assert activated.events[-1].status == "RESOLVED"
