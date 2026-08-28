from unittest.mock import Mock

import pytest

from src.packages.core.replanning.application.runtime import ReplanningRuntimeStore


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
