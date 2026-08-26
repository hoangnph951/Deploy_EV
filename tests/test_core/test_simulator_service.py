from pathlib import Path

import pytest

from src.packages.contracts.simulator import SimulationStartRequest
from src.packages.core.simulator.application.catalog_service import PROFILES, SimulationCatalogService
from src.packages.core.simulator.application.simulator_service import SimulatorService

LOG_DIRECTORY = Path(__file__).resolve().parents[2] / "log_F1"


def ready_case(catalog: SimulationCatalogService, profile: str):
    return next(item for item in catalog.catalog().cases if item.profile == profile and item.readiness == "READY")


def run_to_trigger(profile: str):
    catalog = SimulationCatalogService(LOG_DIRECTORY)
    service = SimulatorService(catalog)
    case = ready_case(catalog, profile)
    run = service.start(
        "owner-1",
        SimulationStartRequest(case_id=case.case_id, speed_multiplier=10, idempotency_key=f"key-{profile}"),
    )
    for _ in range(11):
        run = service.step("owner-1", run.run_id)
    return run


def test_catalog_builds_six_profiles_per_valid_f1_log_and_reports_target():
    response = SimulationCatalogService(LOG_DIRECTORY).catalog()

    assert response.available_base_log_count > 0
    assert response.available_base_log_count <= 15
    assert response.generated_case_count == response.available_base_log_count * len(PROFILES)
    assert response.target_case_count == 90
    assert {item.profile for item in response.cases} == set(PROFILES)
    normal_cases = [item for item in response.cases if item.profile == "NORMAL"]
    business_keys = {
        (item.origin_name.casefold(), item.destination_name.casefold(), item.initial_soc_percent)
        for item in normal_cases
    }
    assert len(business_keys) == len(normal_cases)


def test_normal_profile_never_emits_event_or_calls_agent():
    run = run_to_trigger("NORMAL")
    assert run.status == "RUNNING"
    assert len(run.route_polyline) >= 2
    assert run.charging_stations
    assert run.charging_stations[0].station_id
    assert run.monitoring_events == []
    assert run.agent_decisions == []


@pytest.mark.parametrize(
    ("profile", "event_type", "intent", "action"),
    [
        ("ROUTE_DEVIATION", "ROUTE_DEVIATION", "ROUTE_RECOVERY", "PROPOSE_REPLAN"),
        ("SOC_UNDERPERFORMANCE", "SOC_UNDERPERFORMANCE", "ENERGY_RESCUE", "PROPOSE_REPLAN"),
        ("STATION_UNAVAILABLE", "STATION_UNAVAILABLE", "STATION_SUBSTITUTION", "PROPOSE_REPLAN"),
        ("STALE_TELEMETRY", "STALE_TELEMETRY", "TELEMETRY_RECOVERY", "REQUEST_NEW_TELEMETRY"),
        (
            "NO_FEASIBLE_ALTERNATIVE",
            "STATION_UNAVAILABLE",
            "ENERGY_RESCUE",
            "PROPOSE_REPLAN",
        ),
    ],
)
def test_profiles_drive_the_expected_f3_event_and_f4_decision(profile, event_type, intent, action):
    run = run_to_trigger(profile)
    assert run.status == "AWAITING_ACTION"
    assert run.requires_user_action is True
    assert event_type in {item.event_type for item in run.monitoring_events}
    decision = run.agent_decisions[-1]
    assert decision.intent == intent
    assert decision.action == action
    assert decision.selected_tools
    if profile == "STALE_TELEMETRY":
        assert decision.candidate_plan is None
        assert decision.plan_diff is None
    elif profile not in {"NO_FEASIBLE_ALTERNATIVE", "STATION_UNAVAILABLE"}:
        assert decision.plan_diff is not None
        assert decision.candidate_plan is not None


def test_station_unavailable_excludes_failed_station_before_calling_f1():
    run = run_to_trigger("STATION_UNAVAILABLE")
    decision = run.agent_decisions[-1]

    assert decision.plan_diff is not None
    assert decision.plan_diff.removed_station_ids
    assert decision.plan_diff.added_station_ids == []
    assert decision.candidate_plan is None
    assert "SIMULATED_REPLACEMENT_SELECTED" not in decision.reason_codes


def test_soc_underperformance_agent_includes_nearest_then_expanded_station_search():
    run = run_to_trigger("SOC_UNDERPERFORMANCE")
    decision = run.agent_decisions[-1]

    assert decision.intent == "ENERGY_RESCUE"
    assert decision.selected_tools[:2] == [
        "nearest_station_reachability",
        "station_search",
    ]
    assert "feasibility_check" in decision.selected_tools


def test_stale_telemetry_requires_a_fresh_sample_before_resuming():
    catalog = SimulationCatalogService(LOG_DIRECTORY)
    service = SimulatorService(catalog)
    case = ready_case(catalog, "STALE_TELEMETRY")
    run = service.start(
        "owner-1",
        SimulationStartRequest(case_id=case.case_id, speed_multiplier=10, idempotency_key="stale-refresh"),
    )
    for _ in range(11):
        run = service.step("owner-1", run.run_id)

    assert run.status == "AWAITING_ACTION"
    stale_tick = run.current_tick
    refreshed = service.refresh_telemetry("owner-1", run.run_id)

    assert refreshed.status == "RUNNING"
    assert refreshed.current_tick == stale_tick + 1
    assert refreshed.telemetry is not None
    assert refreshed.telemetry.age_seconds == 0


def test_station_replan_uses_f1_result_and_exposes_replacement_stations():
    catalog = SimulationCatalogService(LOG_DIRECTORY)
    service = SimulatorService(catalog)
    case = next(
        item for item in catalog.catalog().cases
        if item.profile == "STATION_UNAVAILABLE"
        and item.readiness == "READY"
        and item.origin_name == "Ha Noi, Viet Nam"
    )
    started = service.start(
        "owner-1",
        SimulationStartRequest(case_id=case.case_id, speed_multiplier=10, idempotency_key="station-replan"),
    )
    run = started
    for _ in range(20):
        run = service.step("owner-1", run.run_id)
        if run.status == "AWAITING_ACTION":
            break

    failed_station_id = run.monitoring_events[-1].station_id
    replanned = service.replan("owner-1", run.run_id)
    candidate_station_ids = {
        station.station_id for station in replanned.replanned_plan.charging_stops
    }

    assert candidate_station_ids
    assert failed_station_id not in candidate_station_ids
    assert replanned.agent_decisions[-1].candidate_plan is not None
    assert "SIMULATED_REPLACEMENT_SELECTED" not in replanned.agent_decisions[-1].reason_codes
    assert candidate_station_ids <= {station.station_id for station in replanned.charging_stations}


def test_incident_stops_vehicle_until_user_runs_real_f1_replan():
    catalog = SimulationCatalogService(LOG_DIRECTORY)
    service = SimulatorService(catalog)
    case = ready_case(catalog, "ROUTE_DEVIATION")
    run = service.start(
        "owner-1",
        SimulationStartRequest(case_id=case.case_id, speed_multiplier=10, idempotency_key="replan-flow"),
    )
    for _ in range(11):
        run = service.step("owner-1", run.run_id)

    assert run.status == "AWAITING_ACTION"
    assert run.requires_user_action is True
    incident_tick = run.current_tick
    held = service.step("owner-1", run.run_id)
    assert held.current_tick == incident_tick

    replanned = service.replan("owner-1", run.run_id)
    assert replanned.status == "RUNNING"
    assert replanned.requires_user_action is False
    assert replanned.applied_action == "PROPOSE_REPLAN"
    assert replanned.replanned_plan is not None
    assert replanned.replanned_plan.trigger_reason == "F4_REPLAN"
    assert [list(point) for point in replanned.route_polyline] == replanned.replanned_plan.route.polyline
    assert replanned.replanned_plan.route.polyline[0][0] == pytest.approx(run.telemetry.lat)
    assert replanned.replanned_plan.route.polyline[0][1] == pytest.approx(run.telemetry.lng)
    assert replanned.actual_path
    assert replanned.original_route_polyline


def test_run_is_owner_scoped_and_start_is_idempotent():
    catalog = SimulationCatalogService(LOG_DIRECTORY)
    service = SimulatorService(catalog)
    case = ready_case(catalog, "NORMAL")
    request = SimulationStartRequest(case_id=case.case_id, speed_multiplier=5, idempotency_key="same-key")

    first = service.start("owner-1", request)
    second = service.start("owner-1", request)
    assert first.run_id == second.run_id
    with pytest.raises(PermissionError):
        service.get("owner-2", first.run_id)
