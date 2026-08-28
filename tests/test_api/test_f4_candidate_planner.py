from types import SimpleNamespace

from src.apps.api.routes.replanning import TripServiceCandidatePlanner


class FakeTripService:
    def __init__(self, plan):
        self.plan = plan

    def get_trip_plans(self, trip_id: str, owner_id: str):
        return SimpleNamespace(plans=[self.plan])


class EmptyTripService:
    def get_trip_plans(self, trip_id: str, owner_id: str):
        return SimpleNamespace(plans=[])


class CapturingTripService(EmptyTripService):
    def __init__(self):
        self.generate_kwargs = None

    def generate_trip_plan(self, trip_id: str, owner_id: str, **kwargs):
        self.generate_kwargs = kwargs
        payload = {
            "outcome": "PLAN_CREATED",
            "plan": {
                "version": 4,
                "route": {
                    "distance_km": 70.0, "duration_min": 80.0,
                    "polyline": [[21.0, 105.0], [20.0, 106.0]],
                },
                "charging_stops": [
                    {"station_id": "ST-NEW"}, {"station_id": "ST-KEEP"},
                ],
                "soc_points": [{"soc_percent": 20.0}],
                "final_arrival_soc_percent": 20.0,
                "risk_assessment": {"verdict": "FEASIBLE", "is_feasible": True},
            },
            "alternatives": [],
        }
        return SimpleNamespace(model_dump=lambda mode: payload)


class DirectRouteTripService(CapturingTripService):
    def generate_trip_plan(self, trip_id: str, owner_id: str, **kwargs):
        self.generate_kwargs = kwargs
        payload = {
            "outcome": "PLAN_CREATED",
            "plan": {
                "version": 4,
                "route": {
                    "distance_km": 40.0, "duration_min": 50.0,
                    "polyline": [[21.0, 105.0], [20.5, 105.5]],
                },
                "charging_stops": [],
                "soc_points": [{"soc_percent": 20.0}],
                "final_arrival_soc_percent": 20.0,
                "risk_assessment": {"verdict": "FEASIBLE", "is_feasible": True},
            },
            "alternatives": [],
        }
        return SimpleNamespace(model_dump=lambda mode: payload)


def confirmed_plan():
    return SimpleNamespace(
        version=3,
        route=SimpleNamespace(distance_km=100.0, duration_min=120.0),
        charging_stops=[
            SimpleNamespace(station_id="ST-PAST", distance_from_origin_km=10.0),
            SimpleNamespace(station_id="ST-FAILED", distance_from_origin_km=50.0),
            SimpleNamespace(station_id="ST-KEEP", distance_from_origin_km=80.0),
        ],
        soc_points=[
            SimpleNamespace(distance_km=0.0, soc_percent=80.0),
            SimpleNamespace(distance_km=50.0, soc_percent=30.0),
            SimpleNamespace(distance_km=100.0, soc_percent=20.0),
        ],
        final_arrival_soc_percent=20.0,
    )


def test_projector_checks_only_stations_ahead_of_vehicle() -> None:
    planner = TripServiceCandidatePlanner(FakeTripService(confirmed_plan()), "owner")

    past = planner.project_remaining_plan(
        trip_id="trip-1", base_plan_version=3, traveled_distance_km=30.0,
        excluded_station_ids=["ST-PAST"],
    )
    ahead = planner.project_remaining_plan(
        trip_id="trip-1", base_plan_version=3, traveled_distance_km=30.0,
        excluded_station_ids=["ST-FAILED"],
    )

    assert past["remaining_station_ids"] == ["ST-FAILED", "ST-KEEP"]
    assert past["station_unavailable_affects_remaining_trip"] is False
    assert ahead["station_unavailable_affects_remaining_trip"] is True
    assert ahead["unaffected_remaining_station_ids"] == ["ST-KEEP"]


def test_missing_confirmed_plan_never_claims_station_is_unaffected() -> None:
    planner = TripServiceCandidatePlanner(EmptyTripService(), "owner")

    projection = planner.project_remaining_plan(
        trip_id="trip-1", base_plan_version=3, traveled_distance_km=30.0,
        excluded_station_ids=["ST-FAILED"],
    )

    assert projection["station_unavailable_affects_remaining_trip"] is None


def test_minimal_substitution_preserves_unaffected_station_order() -> None:
    plan_that_drops_existing_stop = {
        "version": 4,
        "charging_stops": [{"station_id": "ST-NEW"}],
        "risk_assessment": {"verdict": "FEASIBLE", "is_feasible": True},
    }
    minimal_plan = {
        "version": 5,
        "charging_stops": [
            {"station_id": "ST-NEW"}, {"station_id": "ST-KEEP"},
        ],
        "risk_assessment": {"verdict": "FEASIBLE", "is_feasible": True},
    }

    selected = TripServiceCandidatePlanner._select_minimal_substitution(
        [plan_that_drops_existing_stop, minimal_plan],
        unaffected_station_ids=["ST-KEEP"],
        excluded_station_ids=["ST-FAILED"],
    )

    assert selected["version"] == 5


def test_minimal_substitution_requires_a_new_station_for_an_affected_stop() -> None:
    direct_plan_without_replacement = {
        "version": 4,
        "charging_stops": [],
        "risk_assessment": {"verdict": "FEASIBLE", "is_feasible": True},
    }

    selected = TripServiceCandidatePlanner._select_minimal_substitution(
        [direct_plan_without_replacement],
        unaffected_station_ids=[],
        excluded_station_ids=["ST-FAILED"],
        replacement_required=True,
        original_station_ids=["ST-FAILED"],
    )

    assert selected is None


def test_minimal_substitution_cannot_reuse_an_old_passed_station_as_the_replacement() -> None:
    route_reusing_old_station = {
        "version": 4,
        "charging_stops": [{"station_id": "ST-PAST"}],
        "risk_assessment": {"verdict": "FEASIBLE", "is_feasible": True},
    }

    selected = TripServiceCandidatePlanner._select_minimal_substitution(
        [route_reusing_old_station],
        unaffected_station_ids=[],
        excluded_station_ids=["ST-FAILED"],
        replacement_required=True,
        original_station_ids=["ST-PAST", "ST-FAILED"],
    )

    assert selected is None


def test_minimal_strategy_is_applied_before_f1_primary_is_persisted() -> None:
    service = CapturingTripService()
    planner = TripServiceCandidatePlanner(service, "owner")

    result = planner.build_candidate(
        trip_id="trip-1", current_lat=21.0, current_lon=105.0,
        current_soc_percent=40.0, base_plan_version=3, context_version=5,
        excluded_station_ids=["ST-FAILED"], remaining_station_ids=["ST-FAILED", "ST-KEEP"],
        unaffected_remaining_station_ids=["ST-KEEP"], current_plan_projection={},
        strategy="MINIMAL_SUBSTITUTION",
    )

    assert service.generate_kwargs["preferred_station_ids"] == ["ST-KEEP"]
    assert service.generate_kwargs["require_station_substitution"] is False
    assert result["strategy"] == "MINIMAL_SUBSTITUTION"
    assert result["plan_version"] == 4


def test_affected_station_cannot_be_claimed_as_minimally_substituted_by_direct_route() -> None:
    service = DirectRouteTripService()
    planner = TripServiceCandidatePlanner(service, "owner")

    result = planner.build_candidate(
        trip_id="trip-1", current_lat=21.0, current_lon=105.0,
        current_soc_percent=40.0, base_plan_version=3, context_version=5,
        excluded_station_ids=["ST-FAILED"], remaining_station_ids=["ST-FAILED"],
        unaffected_remaining_station_ids=[],
        current_plan_projection={
            "affected_excluded_station_ids": ["ST-FAILED"],
            "original_station_ids": ["ST-FAILED"],
        },
        strategy="MINIMAL_SUBSTITUTION",
    )

    assert service.generate_kwargs["require_station_substitution"] is True
    assert result["feasibility_verdict"] == "STRATEGY_NOT_SATISFIED"


def test_full_replan_is_rejected_if_f1_returns_a_blacklisted_station() -> None:
    service = CapturingTripService()
    planner = TripServiceCandidatePlanner(service, "owner")

    result = planner.build_candidate(
        trip_id="trip-1", current_lat=21.0, current_lon=105.0,
        current_soc_percent=40.0, base_plan_version=3, context_version=5,
        excluded_station_ids=["ST-NEW"], remaining_station_ids=["ST-NEW"],
        unaffected_remaining_station_ids=[], current_plan_projection={},
        strategy="FULL_REPLAN",
    )

    assert result["feasibility_verdict"] == "INSUFFICIENT_EVIDENCE"
    assert result["validation_reason"] == "BLACKLISTED_STATION_IN_CANDIDATE"


def test_full_replan_is_rejected_if_route_does_not_start_near_current_gps() -> None:
    service = DirectRouteTripService()
    planner = TripServiceCandidatePlanner(service, "owner")

    result = planner.build_candidate(
        trip_id="trip-1", current_lat=10.0, current_lon=106.0,
        current_soc_percent=40.0, base_plan_version=3, context_version=5,
        excluded_station_ids=[], remaining_station_ids=[],
        unaffected_remaining_station_ids=[], current_plan_projection={},
        strategy="FULL_REPLAN",
    )

    assert result["feasibility_verdict"] == "INSUFFICIENT_EVIDENCE"
    assert result["validation_reason"] == "REPLAN_ORIGIN_MISMATCH"
