from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event, inspect

from src.packages.contracts.monitoring import MonitoringEvent, TelemetrySnapshot
from src.packages.contracts.replanning import ActiveConstraintContext, TripContextSnapshot
from src.packages.core.replanning.application.service import ReplanningService
from src.packages.core.replanning.infrastructure import models as _replanning_models  # noqa: F401
from src.packages.core.replanning.infrastructure.repository import SqlAlchemyReplanningAuditRepository
from src.packages.core.trips.infrastructure.database import Base
from src.packages.core.trips.infrastructure.models import TripModel


def test_f4_audit_tables_are_registered_and_creatable() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    tables = set(inspect(engine).get_table_names())

    assert {
        "monitoring_events",
        "decision_epochs",
        "decision_epoch_events",
        "trip_context_snapshots",
        "agent_runs",
        "agent_run_events",
        "tool_runs",
        "planning_runs",
        "plan_diffs",
        "plan_version_events",
    } <= tables


def test_get_latest_context_returns_highest_persisted_version(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'f4-context-hydration.db').as_posix()}"
    repository = SqlAlchemyReplanningAuditRepository(database_url)
    Base.metadata.create_all(repository.engine)
    now = datetime.now(UTC)
    with repository.session_factory() as session:
        session.add(TripModel(
            id="trip-hydrate", owner_id="owner", status="ACTIVE",
            origin_address="A", origin_lat=21.0, origin_lng=105.0,
            origin_source_type="MANUAL", destination_address="B",
            destination_lat=20.0, destination_lng=106.0,
            destination_source_type="MANUAL", initial_soc_percent=80,
            soc_source_type="MANUAL", vehicle_profile_id="vehicle",
            preference="balanced", assumptions_json={}, created_at=now,
            updated_at=now, confirmed_plan_version=1,
        ))
        for version in (2, 3):
            context = TripContextSnapshot(
                trip_id="trip-hydrate", context_version=version,
                current_confirmed_plan_version=1,
                pending_plan_version=version,
                telemetry_snapshot_id=f"telemetry-{version}",
                current_lat=21, current_lng=105,
                current_soc_percent=65 - version,
                destination_lat=20, destination_lng=106,
                vehicle_profile_version="vehicle-v1", policy_version="policy-v1",
                assumption_snapshot_id=f"assumption-{version}",
                unresolved_constraints=ActiveConstraintContext(), created_at=now,
            )
            session.add(_replanning_models.TripContextSnapshotModel(
                id=f"context-{version}", trip_id=context.trip_id,
                context_version=context.context_version,
                telemetry_snapshot_id=context.telemetry_snapshot_id,
                confirmed_plan_version=context.current_confirmed_plan_version,
                pending_plan_version=context.pending_plan_version,
                snapshot_json=context.model_dump(mode="json"), created_at=context.created_at,
            ))
        session.commit()

    context = repository.get_latest_context("trip-hydrate")

    assert context is not None
    assert context.context_version == 3
    assert context.telemetry_snapshot_id == "telemetry-3"

    with repository.session_factory() as session:
        row = session.get(_replanning_models.TripContextSnapshotModel, "context-3")
        row.snapshot_json = {**row.snapshot_json, "context_version": 2}
        session.commit()

    with pytest.raises(ValueError, match="identity does not match"):
        repository.get_latest_context("trip-hydrate")


def test_save_run_respects_parent_foreign_keys(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'f4-audit.db').as_posix()}"
    repository = SqlAlchemyReplanningAuditRepository(database_url)

    @event.listens_for(repository.engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(repository.engine)
    now = datetime.now(UTC)
    with repository.session_factory() as session:
        session.add(TripModel(
            id="trip-fk", owner_id="owner", status="ACTIVE",
            origin_address="A", origin_lat=21.0, origin_lng=105.0,
            origin_source_type="MANUAL", destination_address="B",
            destination_lat=20.0, destination_lng=106.0,
            destination_source_type="MANUAL", initial_soc_percent=80,
            soc_source_type="MANUAL", vehicle_profile_id="vehicle",
            preference="balanced", assumptions_json={}, created_at=now,
            updated_at=now, confirmed_plan_version=1,
        ))
        session.commit()

    context = TripContextSnapshot(
        trip_id="trip-fk", context_version=1, current_confirmed_plan_version=1,
        telemetry_snapshot_id="telemetry-fk", current_lat=21, current_lng=105,
        current_soc_percent=65, destination_lat=20, destination_lng=106,
        vehicle_profile_version="vehicle-v1", policy_version="policy-v1",
        assumption_snapshot_id="assumption-fk",
        unresolved_constraints=ActiveConstraintContext(), created_at=now,
    )
    telemetry = TelemetrySnapshot(
        snapshot_id="telemetry-fk", lat=21, lon=105, soc_percent=65,
        expected_soc_percent=71, speed_kph=60, distance_km=10,
        progress_percent=35, recorded_at=now,
    )
    monitoring_event = MonitoringEvent(
        event_id="event-fk", trip_id="trip-fk", event_type="SOC_UNDERPERFORMANCE",
        occurred_at=now, received_at=now, telemetry_snapshot_id="telemetry-fk",
        related_plan_version=1, severity="HIGH", correlation_id="corr-fk",
    )
    planner = type("Planner", (), {"build_candidate": lambda self, **kwargs: {
        "plan_version": 2, "feasibility_verdict": "FEASIBLE",
    }})()
    outcome = ReplanningService(planner=planner).process(
        previous_context=context, telemetry=telemetry, events=[monitoring_event],
    )

    repository.save_run(outcome, [monitoring_event])

    with repository.session_factory() as session:
        assert session.get(_replanning_models.AgentRunModel, outcome.agent_run_id) is not None
        assert session.get(
            _replanning_models.AgentRunEventModel,
            (outcome.agent_run_id, monitoring_event.event_id),
        ) is not None
        planning_run = session.get(_replanning_models.PlanningRunModel, outcome.agent_run_id)
        assert planning_run.request_snapshot == {
            "trip_id": "trip-fk",
            "context_version": 2,
            "telemetry_snapshot_id": "telemetry-fk",
            "event_ids": ["event-fk"],
            "event_types": ["SOC_UNDERPERFORMANCE"],
        }


def test_save_run_accepts_insufficient_evidence_status(tmp_path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'f4-stale-audit.db').as_posix()}"
    repository = SqlAlchemyReplanningAuditRepository(database_url)
    Base.metadata.create_all(repository.engine)
    now = datetime.now(UTC)
    with repository.session_factory() as session:
        session.add(TripModel(
            id="trip-stale", owner_id="owner", status="ACTIVE",
            origin_address="A", origin_lat=21.0, origin_lng=105.0,
            origin_source_type="MANUAL", destination_address="B",
            destination_lat=20.0, destination_lng=106.0,
            destination_source_type="MANUAL", initial_soc_percent=80,
            soc_source_type="MANUAL", vehicle_profile_id="vehicle",
            preference="balanced", assumptions_json={}, created_at=now,
            updated_at=now, confirmed_plan_version=1,
        ))
        session.commit()

    context = TripContextSnapshot(
        trip_id="trip-stale", context_version=1, current_confirmed_plan_version=1,
        telemetry_snapshot_id="telemetry-stale", current_lat=21, current_lng=105,
        current_soc_percent=65, destination_lat=20, destination_lng=106,
        vehicle_profile_version="vehicle-v1", policy_version="policy-v1",
        assumption_snapshot_id="assumption-stale",
        unresolved_constraints=ActiveConstraintContext(), created_at=now,
    )
    telemetry = TelemetrySnapshot(
        snapshot_id="telemetry-stale", lat=21, lon=105, soc_percent=65,
        expected_soc_percent=71, speed_kph=0, distance_km=10,
        progress_percent=35, freshness="STALE", recorded_at=now,
    )
    monitoring_event = MonitoringEvent(
        event_id="event-stale", trip_id="trip-stale", event_type="STALE_TELEMETRY",
        occurred_at=now, received_at=now, telemetry_snapshot_id="telemetry-stale",
        related_plan_version=1, severity="HIGH", correlation_id="corr-stale",
    )
    planner = type("Planner", (), {
        "build_candidate": lambda self, **kwargs: (_ for _ in ()).throw(
            AssertionError("stale telemetry must not invoke planning")
        )
    })()
    outcome = ReplanningService(planner=planner).process(
        previous_context=context, telemetry=telemetry, events=[monitoring_event],
    )

    repository.save_run(outcome, [monitoring_event])

    with repository.session_factory() as session:
        planning_run = session.get(_replanning_models.PlanningRunModel, outcome.agent_run_id)
        assert planning_run.status == "INSUFFICIENT_EVIDENCE"
