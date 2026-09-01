from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.packages.contracts.replanning import ActiveConstraintContext, TripContextSnapshot
from src.packages.core.replanning.application.runtime import ReplanningRuntimeStore


def test_initial_context_hydrates_latest_persisted_snapshot_after_restart() -> None:
    persisted = TripContextSnapshot(
        trip_id="trip-restart",
        context_version=2,
        current_confirmed_plan_version=1,
        pending_plan_version=3,
        telemetry_snapshot_id="telemetry-persisted",
        current_lat=20.8,
        current_lng=105.3,
        current_soc_percent=62.1,
        destination_lat=21.0,
        destination_lng=105.8,
        vehicle_profile_version="vehicle-v1",
        policy_version="policy-v1",
        assumption_snapshot_id="assumption-persisted",
        active_event_ids=["event-persisted"],
        unresolved_constraints=ActiveConstraintContext(route_deviation_active=True),
        created_at=datetime.now(UTC),
    )
    repository = Mock()
    repository.get_latest_context.return_value = persisted
    store = ReplanningRuntimeStore(audit_repository=repository)
    trip = SimpleNamespace(
        trip_id="trip-restart",
        origin=SimpleNamespace(lat=20.0, lng=105.0),
        destination=SimpleNamespace(lat=21.0, lng=105.8),
        initial_soc=SimpleNamespace(value_percent=21.0),
        assumptions=SimpleNamespace(
            vehicle_profile_version="vehicle-v1",
            policy_version="policy-v1",
        ),
        confirmed_plan_version=1,
    )

    context = store.initial_context(trip, plan_count=3, pending_plan_version=3)

    assert context == persisted
    assert store.contexts[trip.trip_id] == persisted
    repository.get_latest_context.assert_called_once_with(trip.trip_id)


@pytest.mark.parametrize(
    ("confirmed_plan_version", "pending_plan_version"),
    [(2, None), (1, None), (1, 3)],
)
def test_hydrated_context_reconciles_authoritative_plan_state(
    confirmed_plan_version: int,
    pending_plan_version: int | None,
) -> None:
    persisted = TripContextSnapshot(
        trip_id="trip-plan-decision",
        context_version=2,
        current_confirmed_plan_version=1,
        pending_plan_version=2,
        telemetry_snapshot_id="telemetry-persisted",
        current_lat=20.8,
        current_lng=105.3,
        current_soc_percent=62.1,
        destination_lat=21.0,
        destination_lng=105.8,
        vehicle_profile_version="vehicle-v1",
        policy_version="policy-v1",
        assumption_snapshot_id="assumption-persisted",
        created_at=datetime.now(UTC),
    )
    repository = Mock()
    repository.get_latest_context.return_value = persisted
    store = ReplanningRuntimeStore(audit_repository=repository)
    trip = SimpleNamespace(trip_id="trip-plan-decision", confirmed_plan_version=confirmed_plan_version)

    context = store.initial_context(
        trip,
        plan_count=3,
        pending_plan_version=pending_plan_version,
    )

    assert context.context_version == 2
    assert context.current_confirmed_plan_version == confirmed_plan_version
    assert context.pending_plan_version == pending_plan_version


def test_failed_audit_write_does_not_mutate_runtime_state() -> None:
    repository = Mock()
    repository.save_run.side_effect = RuntimeError("database unavailable")
    store = ReplanningRuntimeStore(audit_repository=repository)
    outcome = Mock()
    outcome.context.trip_id = "trip-retry"
    outcome.agent_run_id = "run-retry"

    with pytest.raises(RuntimeError, match="database unavailable"):
        store.save("owner-retry", outcome, [])

    assert store.contexts == {}
    assert store.owners == {}
    assert store.events == {}
    assert store.runs == {}
