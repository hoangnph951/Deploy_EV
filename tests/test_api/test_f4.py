import asyncio
import json
from datetime import UTC, datetime

import pytest

from src.apps.api.bootstrap.config import get_settings
from src.apps.api.main import app
from src.apps.api.routes.replanning import get_replanning_supervisor
from src.packages.agent.replanning.fallback import ConservativeSupervisor


class _RecordingSupervisor(ConservativeSupervisor):
    def __init__(self):
        self.assess_calls: list[list[str]] = []

    def assess(self, **kwargs):
        self.assess_calls.append(kwargs["event_types"])
        return super().assess(**kwargs)


async def _fault_replan_payload(client, owner: str, *, source: str, fault: str):
    created = await client.post(
        "/api/v1/trips",
        json={
            "origin": {"address": "Ha Noi", "lat": None, "lng": None, "source_type": "MANUAL"},
            "destination": {"address": "Vinh", "lat": None, "lng": None, "source_type": "MANUAL"},
            "initial_soc_percent": 80,
            "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1",
            "preference": "balanced",
        },
        headers={"X-User-Id": owner},
    )
    trip_id = created.json()["trip_id"]
    now = datetime.now(UTC).isoformat()
    return trip_id, {
        "simulation_fault": fault,
        "telemetry": {
            "snapshot_id": f"telemetry-{owner}",
            "lat": 21.0,
            "lon": 105.0,
            "soc_percent": 60,
            "expected_soc_percent": 66,
            "speed_kph": 0,
            "distance_km": 1,
            "progress_percent": 1,
            "freshness": "FRESH",
            "source": source,
            "recorded_at": now,
        },
        "events": [{
            "event_id": f"event-{owner}",
            "trip_id": trip_id,
            "event_type": "SOC_UNDERPERFORMANCE",
            "occurred_at": now,
            "received_at": now,
            "telemetry_snapshot_id": f"telemetry-{owner}",
            "related_plan_version": 0,
            "severity": "HIGH",
            "correlation_id": f"corr-{owner}",
        }],
    }


def test_replanning_supervisor_dependency_keeps_test_mode_conservative():
    settings = get_settings()

    assert settings.app_env == "test"
    assert isinstance(
        get_replanning_supervisor(settings),
        ConservativeSupervisor,
    )


@pytest.mark.asyncio
async def test_replanning_supervisor_dependency_override_reaches_submit_and_stream(
    client,
):
    supervisor = _RecordingSupervisor()
    app.dependency_overrides[get_replanning_supervisor] = lambda: supervisor
    try:
        trip_id, payload = await _fault_replan_payload(
            client,
            "owner-supervisor-submit",
            source="REAL_GPS",
            fault="NONE",
        )
        submitted = await client.post(
            f"/api/v1/trips/{trip_id}/replans",
            headers={"X-User-Id": "owner-supervisor-submit"},
            json=payload,
        )

        stream_trip_id, stream_payload = await _fault_replan_payload(
            client,
            "owner-supervisor-stream",
            source="REAL_GPS",
            fault="NONE",
        )
        streamed = await client.post(
            f"/api/v1/trips/{stream_trip_id}/replans/stream",
            headers={"X-User-Id": "owner-supervisor-stream"},
            json=stream_payload,
        )
    finally:
        app.dependency_overrides.pop(get_replanning_supervisor, None)

    assert submitted.status_code == 202
    assert streamed.status_code == 200
    stream_events = [json.loads(line) for line in streamed.text.splitlines()]
    assert stream_events[0]["type"] == "trace"
    assert stream_events[-1]["type"] == "complete"
    assert supervisor.assess_calls == [
        ["SOC_UNDERPERFORMANCE"],
        ["SOC_UNDERPERFORMANCE"],
    ]


@pytest.mark.asyncio
async def test_simulator_capability_and_fault_safety_boundary(client, monkeypatch):
    capabilities = await client.get(
        "/api/v1/simulator/capabilities",
        headers={"X-User-Id": "owner-capabilities"},
    )
    assert capabilities.status_code == 200
    assert capabilities.json() == {"fault_injection_enabled": False}

    trip_id, payload = await _fault_replan_payload(
        client,
        "owner-fault-disabled",
        source="SIMULATED",
        fault="F1_PROVIDER_FAILURE",
    )
    disabled = await client.post(
        f"/api/v1/trips/{trip_id}/replans",
        headers={"X-User-Id": "owner-fault-disabled"},
        json=payload,
    )
    assert disabled.status_code == 403

    monkeypatch.setenv("SIMULATOR_FAULT_INJECTION_ENABLED", "true")
    get_settings.cache_clear()
    try:
        enabled = await client.get(
            "/api/v1/simulator/capabilities",
            headers={"X-User-Id": "owner-capabilities"},
        )
        assert enabled.json() == {"fault_injection_enabled": True}

        trip_id, payload = await _fault_replan_payload(
            client,
            "owner-fault-real",
            source="REAL_GPS",
            fault="F1_PROVEN_INFEASIBLE",
        )
        real_telemetry_fault = await client.post(
            f"/api/v1/trips/{trip_id}/replans",
            headers={"X-User-Id": "owner-fault-real"},
            json=payload,
        )
        assert real_telemetry_fault.status_code == 422
    finally:
        monkeypatch.delenv("SIMULATOR_FAULT_INJECTION_ENABLED")
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_disabled_simulator_fault_is_rejected_before_creating_a_session(client, monkeypatch):
    monkeypatch.setenv("SIMULATOR_FAULT_INJECTION_ENABLED", "false")
    get_settings.cache_clear()
    try:
        owner = "owner-start-fault-disabled"
        created = await client.post(
            "/api/v1/trips",
            json={
                "origin": {"address": "Ha Noi", "lat": None, "lng": None, "source_type": "MANUAL"},
                "destination": {"address": "Hoa Binh", "lat": None, "lng": None, "source_type": "MANUAL"},
                "initial_soc_percent": 85, "soc_source_type": "MANUAL",
                "vehicle_profile_id": "xe-x-mvp-v1", "preference": "balanced",
            },
            headers={"X-User-Id": owner},
        )
        trip_id = created.json()["trip_id"]
        planned = await client.post(f"/api/v1/trips/{trip_id}/plans", headers={"X-User-Id": owner})
        proposal = planned.json()["plan"]
        confirmed = await client.post(
            f"/api/v1/trips/{trip_id}/plans/{proposal['version']}/confirm",
            headers={"X-User-Id": owner},
            json={"expected_plan_version": proposal["version"], "expected_context_version": 1},
        )
        assert confirmed.status_code == 200

        started = await client.post(
            f"/api/v1/simulator/trips/{trip_id}/start",
            headers={"X-User-Id": owner},
            json={
                "plan_id": proposal["plan_id"], "plan": proposal,
                "scenario": "NORMAL", "simulation_fault": "F1_PROVIDER_FAILURE",
            },
        )

        assert started.status_code == 403
        assert started.json()["error"]["code"] == "SIMULATOR_FAULT_INJECTION_DISABLED"
        state = await client.get(f"/api/v1/simulator/trips/{trip_id}", headers={"X-User-Id": owner})
        assert state.status_code == 409
        assert state.json()["error"]["code"] == "SIMULATION_NOT_STARTED"
    finally:
        monkeypatch.delenv("SIMULATOR_FAULT_INJECTION_ENABLED")
        get_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fault", "expected_status"),
    [
        ("F1_PROVIDER_FAILURE", "INSUFFICIENT_EVIDENCE"),
        ("F1_PROVEN_INFEASIBLE", "INFEASIBLE"),
    ],
)
async def test_simulated_f1_fault_reaches_typed_f4_outcome(
    client, monkeypatch, fault, expected_status,
):
    monkeypatch.setenv("SIMULATOR_FAULT_INJECTION_ENABLED", "true")
    get_settings.cache_clear()
    owner = f"owner-{fault.lower()}"
    try:
        trip_id, payload = await _fault_replan_payload(
            client,
            owner,
            source="SIMULATED",
            fault=fault,
        )
        response = await client.post(
            f"/api/v1/trips/{trip_id}/replans",
            headers={"X-User-Id": owner},
            json=payload,
        )
        assert response.status_code == 202
        assert response.json()["status"] == expected_status
    finally:
        monkeypatch.delenv("SIMULATOR_FAULT_INJECTION_ENABLED")
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_cross_user_cannot_mutate_pending_plan_through_f2_or_f4(client):
    owner = "owner-cross-boundary"
    other = "other-cross-boundary"
    created = await client.post(
        "/api/v1/trips",
        json={
            "origin": {"address": "Ha Noi", "lat": None, "lng": None, "source_type": "MANUAL"},
            "destination": {"address": "Hoa Binh", "lat": None, "lng": None, "source_type": "MANUAL"},
            "initial_soc_percent": 85,
            "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1",
            "preference": "balanced",
        },
        headers={"X-User-Id": owner},
    )
    trip_id = created.json()["trip_id"]
    generated = await client.post(
        f"/api/v1/trips/{trip_id}/plans",
        headers={"X-User-Id": owner},
    )
    plan = generated.json()["plan"]
    decision = {
        "expected_plan_version": plan["version"],
        "expected_context_version": 1,
    }

    responses = [
        await client.post(
            f"/api/v1/plans/{plan['plan_id']}/confirm",
            headers={"X-User-Id": other, "If-Match": str(plan["version"])},
        ),
        await client.post(
            f"/api/v1/plans/{plan['plan_id']}/reject",
            headers={
                "X-User-Id": other,
                "If-Match": str(plan["version"]),
                "Content-Type": "application/json",
            },
            json={"reason": "unauthorized"},
        ),
        await client.post(
            f"/api/v1/trips/{trip_id}/plans/{plan['version']}/confirm",
            headers={"X-User-Id": other},
            json=decision,
        ),
        await client.post(
            f"/api/v1/trips/{trip_id}/plans/{plan['version']}/reject",
            headers={"X-User-Id": other},
            json=decision,
        ),
    ]

    assert all(response.status_code in {403, 404} for response in responses)
    plans = await client.get(
        f"/api/v1/trips/{trip_id}/plans",
        headers={"X-User-Id": owner},
    )
    assert plans.json()["plans"][0]["status"] == "PENDING"


@pytest.mark.asyncio
async def test_f4_stream_emits_public_trace_before_complete_outcome(client):
    created = await client.post(
        "/api/v1/trips",
        json={
            "origin": {"address": "Ha Noi", "lat": None, "lng": None, "source_type": "MANUAL"},
            "destination": {"address": "Vinh", "lat": None, "lng": None, "source_type": "MANUAL"},
            "initial_soc_percent": 80, "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1", "preference": "balanced",
        },
        headers={"X-User-Id": "owner-f4-stream"},
    )
    trip_id = created.json()["trip_id"]
    now = datetime.now(UTC).isoformat()
    response = await client.post(
        f"/api/v1/trips/{trip_id}/replans/stream",
        headers={"X-User-Id": "owner-f4-stream"},
        json={
            "telemetry": {
                "snapshot_id": "telemetry-stream", "lat": 21.0, "lon": 105.0,
                "soc_percent": 60, "expected_soc_percent": 65, "speed_kph": 0,
                "distance_km": 0, "progress_percent": 0, "freshness": "STALE",
                "recorded_at": now,
            },
            "events": [{
                "event_id": "event-stream", "trip_id": trip_id,
                "event_type": "STALE_TELEMETRY", "occurred_at": now, "received_at": now,
                "telemetry_snapshot_id": "telemetry-stream", "related_plan_version": 0,
                "severity": "HIGH", "evidence_refs": ["telemetry-stream"],
                "correlation_id": "corr-stream",
            }],
        },
    )

    events = [json.loads(line) for line in response.text.splitlines() if line]
    assert response.status_code == 200
    assert events[0]["type"] == "trace"
    assert events[0]["trace"]["public_summary"]
    assert events[-1]["type"] == "complete"
    assert events[-1]["outcome"]["status"] == "INSUFFICIENT_EVIDENCE"


@pytest.mark.asyncio
async def test_f4_stale_telemetry_returns_structured_audit_without_candidate(client):
    created = await client.post(
        "/api/v1/trips",
        json={
            "origin": {"address": "Ha Noi", "lat": None, "lng": None, "source_type": "MANUAL"},
            "destination": {"address": "Vinh", "lat": None, "lng": None, "source_type": "MANUAL"},
            "initial_soc_percent": 80, "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1", "preference": "balanced",
        },
        headers={"X-User-Id": "owner-f4"},
    )
    trip_id = created.json()["trip_id"]
    now = datetime.now(UTC).isoformat()
    response = await client.post(
        f"/api/v1/trips/{trip_id}/replans",
        headers={"X-User-Id": "owner-f4"},
        json={
            "telemetry": {
                "snapshot_id": "telemetry-1", "lat": 21.0, "lon": 105.0,
                "soc_percent": 60, "expected_soc_percent": 65, "speed_kph": 0,
                "distance_km": 0, "progress_percent": 0, "freshness": "STALE",
                "recorded_at": now,
            },
            "events": [{
                "event_id": "event-stale", "trip_id": trip_id,
                "event_type": "STALE_TELEMETRY", "occurred_at": now, "received_at": now,
                "telemetry_snapshot_id": "telemetry-1", "related_plan_version": 0,
                "severity": "HIGH", "evidence_refs": ["telemetry-1"],
                "correlation_id": "corr-1",
            }],
        },
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "INSUFFICIENT_EVIDENCE"
    assert payload["action"]["action"] == "REQUEST_NEW_TELEMETRY"
    assert payload["candidate"] is None

    audit = await client.get(
        f"/api/v1/agent-runs/{payload['agent_run_id']}",
        headers={"X-User-Id": "owner-f4"},
    )
    assert audit.status_code == 200
    assert audit.json()["assessment"]["primary_objective"] == "RECOVER_TELEMETRY"

    context = await client.get(
        f"/api/v1/trips/{trip_id}/context", headers={"X-User-Id": "owner-f4"}
    )
    assert context.status_code == 200
    assert context.json()["context_version"] == payload["context"]["context_version"]

    events = await client.get(
        f"/api/v1/trips/{trip_id}/events", headers={"X-User-Id": "owner-f4"}
    )
    assert events.status_code == 200
    assert events.json()[0]["event_id"] == "event-stale"

    epoch = await client.get(
        f"/api/v1/trips/{trip_id}/decision-epochs/{payload['epoch']['epoch_id']}",
        headers={"X-User-Id": "owner-f4"},
    )
    assert epoch.status_code == 200
    assert epoch.json()["event_ids"] == ["event-stale"]

    planning = await client.get(
        f"/api/v1/planning-runs/{payload['agent_run_id']}",
        headers={"X-User-Id": "owner-f4"},
    )
    assert planning.status_code == 200
    assert planning.json()["status"] == "INSUFFICIENT_EVIDENCE"

    retry = await client.post(
        f"/api/v1/trips/{trip_id}/replans",
        headers={"X-User-Id": "owner-f4"},
        json={
            "telemetry": {
                "snapshot_id": "telemetry-1", "lat": 21.0, "lon": 105.0,
                "soc_percent": 60, "expected_soc_percent": 65, "speed_kph": 0,
                "distance_km": 0, "progress_percent": 0, "freshness": "STALE",
                "recorded_at": now,
            },
            "events": [{
                "event_id": "event-stale", "trip_id": trip_id,
                "event_type": "STALE_TELEMETRY", "occurred_at": now, "received_at": now,
                "telemetry_snapshot_id": "telemetry-1", "related_plan_version": 0,
                "severity": "HIGH", "evidence_refs": ["telemetry-1"],
                "correlation_id": "corr-1",
            }],
        },
    )
    assert retry.json()["agent_run_id"] == payload["agent_run_id"]
    assert retry.json()["context"]["context_version"] == payload["context"]["context_version"]


@pytest.mark.asyncio
async def test_f4_confirm_rejects_stale_context_and_confirms_current_context(client):
    created = await client.post(
        "/api/v1/trips",
        json={
            "origin": {"address": "Ha Noi", "lat": None, "lng": None, "source_type": "MANUAL"},
            "destination": {"address": "Hoa Binh", "lat": None, "lng": None, "source_type": "MANUAL"},
            "initial_soc_percent": 85, "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1", "preference": "balanced",
        },
        headers={"X-User-Id": "owner-confirm-f4"},
    )
    trip_id = created.json()["trip_id"]
    plan = await client.post(
        f"/api/v1/trips/{trip_id}/plans", headers={"X-User-Id": "owner-confirm-f4"}
    )
    version = plan.json()["plan"]["version"]
    proposal = plan.json()["plan"]

    pending_start = await client.post(
        f"/api/v1/simulator/trips/{trip_id}/start",
        headers={"X-User-Id": "owner-confirm-f4"},
        json={"plan_id": proposal["plan_id"], "plan": proposal, "scenario": "NORMAL"},
    )
    assert pending_start.status_code == 409
    assert pending_start.json()["error"]["code"] == "PLAN_NOT_CONFIRMED"

    stale = await client.post(
        f"/api/v1/trips/{trip_id}/plans/{version}/confirm",
        headers={"X-User-Id": "owner-confirm-f4"},
        json={"expected_plan_version": version, "expected_context_version": 99},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "PLAN_CONTEXT_CHANGED"

    confirmed = await client.post(
        f"/api/v1/trips/{trip_id}/plans/{version}/confirm",
        headers={"X-User-Id": "owner-confirm-f4"},
        json={"expected_plan_version": version, "expected_context_version": 1},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "CONFIRMED"

    confirmed_start = await client.post(
        f"/api/v1/simulator/trips/{trip_id}/start",
        headers={"X-User-Id": "owner-confirm-f4"},
        json={"plan_id": proposal["plan_id"], "plan": proposal, "scenario": "NORMAL"},
    )
    assert confirmed_start.status_code == 200


@pytest.mark.asyncio
async def test_f3_active_simulator_exposes_pause_resume_and_reset_controls(client):
    owner = "owner-f3-controls"
    created = await client.post(
        "/api/v1/trips",
        json={
            "origin": {"address": "Ha Noi", "lat": None, "lng": None, "source_type": "MANUAL"},
            "destination": {"address": "Hoa Binh", "lat": None, "lng": None, "source_type": "MANUAL"},
            "initial_soc_percent": 85, "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1", "preference": "balanced",
        },
        headers={"X-User-Id": owner},
    )
    trip_id = created.json()["trip_id"]
    planned = await client.post(
        f"/api/v1/trips/{trip_id}/plans", headers={"X-User-Id": owner}
    )
    proposal = planned.json()["plan"]
    confirmed = await client.post(
        f"/api/v1/trips/{trip_id}/plans/{proposal['version']}/confirm",
        headers={"X-User-Id": owner},
        json={"expected_plan_version": proposal["version"], "expected_context_version": 1},
    )
    assert confirmed.status_code == 200
    started = await client.post(
        f"/api/v1/simulator/trips/{trip_id}/start",
        headers={"X-User-Id": owner},
        json={
            "plan_id": proposal["plan_id"], "plan": proposal,
            "scenario": "NORMAL", "seed": 210,
        },
    )
    assert started.status_code == 200
    assert started.json()["seed"] == 210

    paused = await client.post(
        f"/api/v1/simulator/trips/{trip_id}/pause", headers={"X-User-Id": owner}
    )
    unchanged = await client.post(
        f"/api/v1/simulator/trips/{trip_id}/tick", headers={"X-User-Id": owner}
    )
    resumed = await client.post(
        f"/api/v1/simulator/trips/{trip_id}/resume", headers={"X-User-Id": owner}
    )
    advanced = await client.post(
        f"/api/v1/simulator/trips/{trip_id}/tick", headers={"X-User-Id": owner}
    )
    reset = await client.post(
        f"/api/v1/simulator/trips/{trip_id}/reset", headers={"X-User-Id": owner}
    )

    assert paused.json()["status"] == "PAUSED"
    assert unchanged.json()["tick_count"] == 0
    assert resumed.json()["status"] == "RUNNING"
    assert advanced.json()["tick_count"] == 1
    assert reset.json()["status"] == "RUNNING"
    assert reset.json()["tick_count"] == 0
    assert reset.json()["telemetry"] is None
    assert reset.json()["seed"] == 210


@pytest.mark.asyncio
async def test_confirmed_replan_history_uses_the_replan_starting_soc(client):
    owner = "owner-f4-history-soc"
    created = await client.post(
        "/api/v1/trips",
        json={
            "origin": {"address": "Ha Noi", "lat": None, "lng": None, "source_type": "MANUAL"},
            "destination": {"address": "Hoa Binh", "lat": None, "lng": None, "source_type": "MANUAL"},
            "initial_soc_percent": 60, "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1", "preference": "balanced",
        },
        headers={"X-User-Id": owner},
    )
    trip_id = created.json()["trip_id"]
    trip = await client.get(f"/api/v1/trips/{trip_id}", headers={"X-User-Id": owner})
    replan = await client.post(
        f"/api/v1/trips/{trip_id}/plans/replan",
        headers={"X-User-Id": owner},
        json={
            "current_lat": trip.json()["origin"]["lat"],
            "current_lon": trip.json()["origin"]["lng"],
            "current_soc_percent": 54.4,
            "excluded_station_ids": [],
        },
    )
    proposal = replan.json()["plan"]
    assert proposal["soc_points"][0]["soc_percent"] == pytest.approx(54.4)
    confirmed = await client.post(
        f"/api/v1/plans/{proposal['plan_id']}/confirm",
        headers={"X-User-Id": owner, "If-Match": str(proposal["version"])},
    )
    assert confirmed.status_code == 200

    history = await client.get("/api/v1/trips/history", headers={"X-User-Id": owner})

    assert history.status_code == 200
    assert history.json()["trips"][0]["initial_soc"]["value_percent"] == pytest.approx(54.4)


@pytest.mark.asyncio
async def test_new_context_marks_existing_pending_plan_stale(client):
    created = await client.post(
        "/api/v1/trips",
        json={
            "origin": {"address": "Ha Noi", "lat": None, "lng": None, "source_type": "MANUAL"},
            "destination": {"address": "Hoa Binh", "lat": None, "lng": None, "source_type": "MANUAL"},
            "initial_soc_percent": 85, "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1", "preference": "balanced",
        }, headers={"X-User-Id": "owner-stale-f4"},
    )
    trip_id = created.json()["trip_id"]
    await client.post(f"/api/v1/trips/{trip_id}/plans", headers={"X-User-Id": "owner-stale-f4"})
    now = datetime.now(UTC).isoformat()
    await client.post(
        f"/api/v1/trips/{trip_id}/replans", headers={"X-User-Id": "owner-stale-f4"},
        json={
            "telemetry": {"snapshot_id": "telemetry-new", "lat": 21, "lon": 105,
                "soc_percent": 70, "expected_soc_percent": 70, "speed_kph": 0,
                "distance_km": 0, "progress_percent": 0, "freshness": "STALE", "recorded_at": now},
            "events": [{"event_id": "event-new", "trip_id": trip_id,
                "event_type": "STALE_TELEMETRY", "occurred_at": now, "received_at": now,
                "telemetry_snapshot_id": "telemetry-new", "related_plan_version": 1,
                "severity": "HIGH", "evidence_refs": ["telemetry-new"], "correlation_id": "corr-new"}],
        },
    )
    plans = await client.get(f"/api/v1/trips/{trip_id}/plans", headers={"X-User-Id": "owner-stale-f4"})
    assert plans.json()["plans"][0]["status"] == "STALE_BY_NEW_CONTEXT"


@pytest.mark.asyncio
async def test_two_concurrent_confirms_allow_exactly_one(client):
    created = await client.post(
        "/api/v1/trips",
        json={
            "origin": {"address": "Ha Noi", "lat": None, "lng": None, "source_type": "MANUAL"},
            "destination": {"address": "Hoa Binh", "lat": None, "lng": None, "source_type": "MANUAL"},
            "initial_soc_percent": 85, "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1", "preference": "balanced",
        }, headers={"X-User-Id": "owner-race-f4"},
    )
    trip_id = created.json()["trip_id"]
    plan = await client.post(f"/api/v1/trips/{trip_id}/plans", headers={"X-User-Id": "owner-race-f4"})
    version = plan.json()["plan"]["version"]

    async def confirm():
        return await client.post(
            f"/api/v1/trips/{trip_id}/plans/{version}/confirm",
            headers={"X-User-Id": "owner-race-f4"},
            json={"expected_plan_version": version, "expected_context_version": 1},
        )

    responses = await asyncio.gather(confirm(), confirm())
    assert sorted(response.status_code for response in responses) == [200, 409]
