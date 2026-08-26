from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from src.packages.contracts.trips import (
    AssumptionSnapshot,
    ChargingStopProposal,
    DataProvenance,
    PlanProposal,
    RiskAssessment,
    RouteGeometry,
)
from src.packages.core.trips.application.planning_run_service import _result_code
from src.packages.core.trips.application.service import TripService
from src.packages.core.trips.domain.entities import PlanVersionRecord, TripRecord
from src.packages.core.trips.infrastructure.models import PlanVersionModel
from src.packages.core.trips.infrastructure.sqlalchemy_repository import (
    SqlAlchemyTripRepository,
)


def _assumptions() -> dict:
    return {
        "policy_version": "policy-v1",
        "reserve_soc_percent": 15.0,
        "ambient_temperature_c": 22.0,
        "vehicle_payload_kg": 150.0,
        "vehicle_profile_version": "vehicle-v1",
        "source": "POLICY_CONFIG",
        "created_at": datetime.now(UTC).isoformat(),
    }


def _repository(tmp_path):
    repository = SqlAlchemyTripRepository(f"sqlite:///{tmp_path / 'plans.db'}")
    repository.ensure_schema()
    now = datetime.now(UTC)
    repository.create_trip(
        TripRecord(
            id="trip-1",
            owner_id="owner-1",
            status="DRAFT",
            origin_address="Origin",
            origin_lat=10.0,
            origin_lng=106.0,
            origin_source_type="MANUAL",
            destination_address="Destination",
            destination_lat=11.0,
            destination_lng=107.0,
            destination_source_type="MANUAL",
            initial_soc_percent=80.0,
            soc_source_type="MANUAL",
            vehicle_profile_id="vinfast-vf6-plus-v1",
            preference="balanced",
            assumptions_json=json.dumps(_assumptions()),
            created_at=now,
            updated_at=now,
        )
    )
    return repository


def _record(*, rank: int, status: str = "PENDING") -> PlanVersionRecord:
    now = datetime.now(UTC)
    plan_id = str(uuid4())
    return PlanVersionRecord(
        id=plan_id,
        trip_id="trip-1",
        version=0,
        status=status,
        assumptions_json=json.dumps(_assumptions()),
        proposal_json=json.dumps(
            {
                "plan_id": plan_id,
                "version": 0,
                "status": status,
                "alternative_rank": rank,
            }
        ),
        created_at=now,
        updated_at=now,
        rank=rank,
        strategy=("BALANCED", "FASTEST", "SAFEST")[rank - 1],
        is_primary=rank == 1,
    )


def test_proposal_is_separate_and_all_ranked_alternatives_are_persisted(tmp_path) -> None:
    repository = _repository(tmp_path)
    version = repository.save_plan_group([_record(rank=1), _record(rank=2), _record(rank=3)])
    assert version == 1

    records = repository.get_plan_versions("trip-1")
    assert [record.rank for record in records] == [1, 2, 3]
    assert {record.version for record in records} == {1}
    assert json.loads(records[0].proposal_json)["version"] == 1
    with repository._session_factory() as session:
        models = session.query(PlanVersionModel).all()
        assert all("proposal" not in model.assumptions for model in models)
        assert all(model.proposal is not None for model in models)


def test_conditional_status_is_persisted(tmp_path) -> None:
    repository = _repository(tmp_path)
    repository.save_plan_group([_record(rank=1, status="CONDITIONAL")])
    record = repository.get_plan_versions("trip-1")[0]
    assert record.status == "CONDITIONAL"
    assert json.loads(record.proposal_json)["status"] == "CONDITIONAL"


def test_legacy_nested_proposal_remains_readable_for_one_release(tmp_path) -> None:
    repository = _repository(tmp_path)
    now = datetime.now(UTC)
    assumptions = _assumptions()
    assumptions["proposal"] = {"plan_id": "legacy-plan", "version": 1}
    with repository._session_factory() as session:
        session.add(
            PlanVersionModel(
                id="legacy-plan",
                trip_id="trip-1",
                version=1,
                status="PENDING",
                rank=1,
                strategy="BALANCED",
                is_primary=True,
                assumptions=assumptions,
                proposal=None,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    record = repository.get_plan_versions("trip-1")[0]
    assert json.loads(record.proposal_json)["plan_id"] == "legacy-plan"
    assert "proposal" not in json.loads(record.assumptions_json)


def test_concurrent_plan_groups_receive_unique_atomic_versions(tmp_path) -> None:
    repository = _repository(tmp_path)

    def save_one(_index: int) -> int:
        return repository.save_plan_group([_record(rank=1)])

    with ThreadPoolExecutor(max_workers=6) as pool:
        versions = list(pool.map(save_one, range(12)))

    assert sorted(versions) == list(range(1, 13))
    records = repository.get_plan_versions("trip-1")
    assert sorted(record.version for record in records) == list(range(1, 13))


def test_openai_recovery_plan_is_returned_and_persisted_as_conditional(tmp_path) -> None:
    repository = _repository(tmp_path)
    now = datetime.now(UTC)
    assumptions = AssumptionSnapshot.model_validate(_assumptions())
    evidence = DataProvenance(
        kind="STATION_DETAIL",
        source="OPENAI_WEB_SEARCH",
        source_url="https://example.test/station-evidence",
        retrieved_at=now,
        version="test-model",
    )
    proposal = PlanProposal(
        plan_id="openai-conditional-plan",
        trip_id="trip-1",
        route=RouteGeometry(
            polyline=[[10.0, 106.0], [11.0, 107.0]],
            distance_km=100,
            duration_min=90,
            retrieved_at=now,
        ),
        charging_stops=[
            ChargingStopProposal(
                station_id="web-station",
                name="Web station",
                lat=10.5,
                lon=106.5,
                arrival_soc_percent=20,
                departure_soc_percent=80,
                charge_duration_min=20,
                energy_added_kwh=30,
                max_power_kw=120,
                connector_type="CCS2",
                station_status="UNVERIFIED",
                provenance=evidence,
            )
        ],
        risk_assessment=RiskAssessment(
            verdict="RISKY",
            level="HIGH_RISK",
            is_feasible=True,
            reason_codes=["UNVERIFIED_STATION_DATA"],
            risk_score=40,
        ),
        assumptions=assumptions,
        provenance=[evidence],
        created_at=now,
    )

    class _Orchestrator:
        def plan(self, _request):
            return SimpleNamespace(
                state={
                    "plan_proposal": proposal,
                    "plan_alternatives": [proposal],
                    "recovery_mode": "OPENAI_STATION_SEARCH",
                }
            )

    response = TripService(
        geocoder=object(),
        repository=repository,
        planning_orchestrator=_Orchestrator(),
    ).generate_trip_plan("trip-1", "owner-1")

    assert response.outcome == "CONDITIONAL"
    assert response.plan.status == "CONDITIONAL"
    record = repository.get_plan_versions("trip-1")[0]
    assert record.status == "CONDITIONAL"


def test_routing_rate_limit_returns_action_required_not_infeasible(tmp_path) -> None:
    repository = _repository(tmp_path)

    class _RateLimitedOrchestrator:
        def plan(self, _request):
            return SimpleNamespace(
                state={
                    "no_feasible_plan": object(),
                    "station_routing_rate_limited": True,
                    "routing_retry_after_seconds": 17.0,
                }
            )

    response = TripService(
        geocoder=object(),
        repository=repository,
        planning_orchestrator=_RateLimitedOrchestrator(),
    ).generate_trip_plan("trip-1", "owner-1")

    assert response.outcome == "ACTION_REQUIRED"
    assert response.provider_status == "RATE_LIMITED"
    assert response.http_status == 429


def test_planning_run_marks_busy_or_unverified_proposals_conditional() -> None:
    busy_proposal = SimpleNamespace(
        risk_assessment=SimpleNamespace(reason_codes=["STATION_BUSY"])
    )
    unverified_proposal = {
        "risk_assessment": {"reason_codes": ["UNVERIFIED_STATION_DATA"]}
    }

    assert _result_code({"plan_proposal": busy_proposal}) == "CONDITIONAL"
    assert _result_code({"plan_proposal": unverified_proposal}) == "CONDITIONAL"


def test_planning_run_marks_environment_fallback_proposal_conditional() -> None:
    fallback_proposal = SimpleNamespace(
        risk_assessment=SimpleNamespace(reason_codes=["ENVIRONMENT_DATA_FALLBACK"])
    )

    assert _result_code({"plan_proposal": fallback_proposal}) == "CONDITIONAL"
