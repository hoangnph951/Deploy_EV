import pytest


async def authenticated_headers(client):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "full_name": "Simulation Demo",
            "email": "simulation@example.com",
            "phone": "0912345678",
            "password": "Matkhau123",
            "password_confirmation": "Matkhau123",
            "accepted_terms": True,
        },
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_simulation_api_lists_cases_starts_and_steps_an_owned_run(client):
    headers = await authenticated_headers(client)
    catalog_response = await client.get("/api/v1/simulation-cases", headers=headers)

    assert catalog_response.status_code == 200
    catalog = catalog_response.json()
    assert catalog["generated_case_count"] == catalog["available_base_log_count"] * 6
    route_case = next(
        item for item in catalog["cases"]
        if item["profile"] == "ROUTE_DEVIATION" and item["readiness"] == "READY"
    )

    started_response = await client.post(
        "/api/v1/simulation-runs",
        headers=headers,
        json={"case_id": route_case["case_id"], "speed_multiplier": 10, "idempotency_key": "api-demo"},
    )
    assert started_response.status_code == 201
    run = started_response.json()
    assert len(run["route_polyline"]) >= 2
    assert run["charging_stations"]
    assert {"station_id", "lat", "lng", "name"} <= run["charging_stations"][0].keys()

    for _ in range(11):
        stepped = await client.post(f"/api/v1/simulation-runs/{run['run_id']}/step", headers=headers)
        assert stepped.status_code == 200
        run = stepped.json()

    assert run["monitoring_events"][-1]["event_type"] == "ROUTE_DEVIATION"
    assert run["agent_decisions"][-1]["intent"] == "ROUTE_RECOVERY"
    assert run["agent_decisions"][-1]["selected_tools"][-1] == "compare_plans"
    assert run["agent_decisions"][-1]["action"] == "PROPOSE_REPLAN"
    assert run["status"] == "AWAITING_ACTION"
    assert run["requires_user_action"] is True
    assert len(run["actual_path"]) == 11
    assert run["original_route_polyline"] == run["route_polyline"]

    replanned_response = await client.post(
        f"/api/v1/simulation-runs/{run['run_id']}/replan",
        headers=headers,
    )
    assert replanned_response.status_code == 200
    replanned = replanned_response.json()
    assert replanned["status"] == "RUNNING"
    assert replanned["replanned_plan"]["trigger_reason"] == "F4_REPLAN"
    assert replanned["route_polyline"] == replanned["replanned_plan"]["route"]["polyline"]
    assert replanned["replanned_plan"]["route"]["provider"] == "TEST_FIXTURE"


@pytest.mark.asyncio
async def test_simulation_api_enforces_run_ownership_in_test_mode(client):
    catalog = (await client.get("/api/v1/simulation-cases", headers={"X-User-Id": "owner-a"})).json()
    normal_case = next(
        item for item in catalog["cases"]
        if item["profile"] == "NORMAL" and item["readiness"] == "READY"
    )
    started = await client.post(
        "/api/v1/simulation-runs",
        headers={"X-User-Id": "owner-a"},
        json={"case_id": normal_case["case_id"], "speed_multiplier": 10, "idempotency_key": "owned-run"},
    )

    response = await client.get(
        f"/api/v1/simulation-runs/{started.json()['run_id']}",
        headers={"X-User-Id": "owner-b"},
    )
    assert response.status_code == 403
