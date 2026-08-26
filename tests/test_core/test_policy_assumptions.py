from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from src.packages.contracts.trips import TripCreateRequest
from src.packages.core.policies.application.assumptions import AssumptionSnapshotService
from src.packages.core.policies.application.service import PolicyConfigService
from src.packages.core.policies.domain.entities import PolicyConfig
from src.packages.core.trips.application.service import TripService
from src.packages.core.trips.infrastructure.models import PlanVersionModel
from src.packages.core.trips.infrastructure.vehicle_fixtures import load_vehicle_profile_fixtures


def make_policy(reserve_soc_percent: float, version: str) -> PolicyConfig:
    return PolicyConfig(
        id=version,
        policy_version=version,
        reserve_soc_percent=reserve_soc_percent,
        stale_station_hours_threshold=24.0,
        route_deviation_km_threshold=2.0,
        active=True,
    )


class MutablePolicyRepository:
    def __init__(self, policy: PolicyConfig):
        self.policy = policy
        self.read_count = 0

    def get_active_policy(self) -> PolicyConfig:
        self.read_count += 1
        return self.policy


class RecordingTripRepository:
    def __init__(self):
        self.vehicle_profile = next(
            profile
            for profile in load_vehicle_profile_fixtures()
            if profile.id == "vinfast-vf6-plus-v1"
        )
        self.created_trip = None

    def get_vehicle_profile(self, requested_id: str):
        if requested_id != self.vehicle_profile.id:
            raise LookupError(requested_id)
        return self.vehicle_profile

    def create_trip(self, trip) -> None:
        self.created_trip = trip


def test_policy_service_caches_until_explicit_reload() -> None:
    repository = MutablePolicyRepository(make_policy(15.0, "pilot-policy-v1"))
    service = PolicyConfigService(repository=repository)

    assert service.get_active_policy().reserve_soc_percent == 15.0
    repository.policy = make_policy(20.0, "pilot-policy-v2")
    assert service.get_active_policy().reserve_soc_percent == 15.0
    assert repository.read_count == 1

    service.clear_cache()
    assert service.get_active_policy().reserve_soc_percent == 20.0
    assert repository.read_count == 2


def test_new_snapshot_uses_updated_policy_without_mutating_old_snapshot() -> None:
    repository = MutablePolicyRepository(make_policy(15.0, "pilot-policy-v1"))
    policy_service = PolicyConfigService(repository=repository)
    snapshot_service = AssumptionSnapshotService()
    vehicle_profile = load_vehicle_profile_fixtures()[0]

    first_snapshot = snapshot_service.create_snapshot(
        policy=policy_service.get_active_policy(),
        vehicle_profile=vehicle_profile,
    )
    repository.policy = make_policy(20.0, "pilot-policy-v2")
    policy_service.clear_cache()
    second_snapshot = snapshot_service.create_snapshot(
        policy=policy_service.get_active_policy(),
        vehicle_profile=vehicle_profile,
    )

    assert first_snapshot.reserve_soc_percent == 15.0
    assert first_snapshot.policy_version == "pilot-policy-v1"
    assert second_snapshot.reserve_soc_percent == 20.0
    assert second_snapshot.policy_version == "pilot-policy-v2"
    assert first_snapshot.reserve_soc_percent == 15.0


def test_trip_snapshot_uses_policy_override_and_contains_all_required_fields() -> None:
    repository = RecordingTripRepository()
    policy_service = PolicyConfigService(override=make_policy(20.0, "test-policy-v20"))
    service = TripService(
        geocoder=object(),
        repository=repository,
        policy_service=policy_service,
        assumption_snapshot_service=AssumptionSnapshotService(),
    )
    request = TripCreateRequest(
        origin={"lat": 21.0278, "lng": 105.8342},
        destination={"lat": 18.6796, "lng": 105.6813},
        initial_soc_percent=80,
    )

    response = service.create_trip(request, owner_id="owner-policy-test")
    persisted_snapshot = json.loads(repository.created_trip.assumptions_json)

    assert response.assumptions.reserve_soc_percent == 20.0
    assert response.assumptions.policy_version == "test-policy-v20"
    assert persisted_snapshot["ambient_temperature_c"] == 25.0
    assert persisted_snapshot["vehicle_payload_kg"] == 150.0
    assert persisted_snapshot["vehicle_profile_version"] == "vinfast_vf6_plus_2025.2"
    assert persisted_snapshot["source"] == "POLICY_CONFIG"
    assert persisted_snapshot["created_at"]
    assert persisted_snapshot["stale_station_hours_threshold"] == 24.0
    assert persisted_snapshot["route_deviation_km_threshold"] == 2.0
    assert persisted_snapshot["planner_algorithm_version"] == "adaptive-beam-v1"
    assert persisted_snapshot["energy_model_version"] == "energy-pilot-v1"
    assert persisted_snapshot["routing_provider"] == "GOONG_DIRECTIONS"
    assert persisted_snapshot["road_version"] == "goong-car-v1"


def test_plan_versions_require_an_assumption_snapshot() -> None:
    assumptions_column = PlanVersionModel.__table__.c.assumptions

    assert assumptions_column.nullable is False

    with pytest.raises(ValueError, match="missing required fields"):
        PlanVersionModel(
            id="plan-without-assumptions",
            trip_id="trip-1",
            version=1,
            status="PENDING_CONFIRMATION",
            assumptions={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
