"""Acceptance and adversarial tests for F2: explain, decide, and trace plans.

These tests are the executable acceptance contract for Feature 2.
"""

from __future__ import annotations

import asyncio

import pytest

OWNER = "f2-owner"
OTHER_USER = "f2-other-user"


async def _create_trip(client, *, owner: str = OWNER, soc: float = 90) -> str:
    response = await client.post(
        "/api/v1/trips",
        json={
            "origin": {
                "address": "Ha Noi",
                "lat": None,
                "lng": None,
                "source_type": "MANUAL",
            },
            "destination": {
                "address": "Vinh",
                "lat": None,
                "lng": None,
                "source_type": "MANUAL",
            },
            "initial_soc_percent": soc,
            "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1",
            "preference": "balanced",
        },
        headers={"X-User-Id": owner},
    )
    assert response.status_code == 201
    return response.json()["trip_id"]


async def _create_plan(client, trip_id: str, *, owner: str = OWNER):
    response = await client.post(
        f"/api/v1/trips/{trip_id}/plans",
        headers={"X-User-Id": owner},
    )
    assert response.status_code == 201
    return response.json()["plan"]


@pytest.mark.asyncio
async def test_f2_plan_is_pending_until_owner_explicitly_confirms(client):
    trip_id = await _create_trip(client)
    plan = await _create_plan(client, trip_id)

    assert plan["status"] == "PENDING"

    trip = await client.get(f"/api/v1/trips/{trip_id}", headers={"X-User-Id": OWNER})
    assert trip.status_code == 200
    assert trip.json()["confirmed_plan_version"] is None


@pytest.mark.asyncio
async def test_f2_deterministic_explanation_uses_only_supported_strategy_reason(client):
    trip_id = await _create_trip(client)
    plan = await _create_plan(client, trip_id)

    expected_reasons = {
        "BALANCED": "Cân bằng thời gian hành trình, thời gian sạc, đường vòng và biên SOC.",
        "FASTEST": "Có tổng thời gian lái và sạc thấp nhất trong các phương án đã xác minh.",
        "SAFEST": "Có biên SOC thấp nhất trên hành trình cao hơn các phương án còn lại.",
    }
    assert plan["explanation_source"] == "DETERMINISTIC"
    assert plan["selection_reason"] == expected_reasons[plan["strategy"]]
    assert plan["selection_reason"].strip()
    explanation = plan["explanation"]
    assert explanation["summary_text"].strip()
    assert explanation["references"]
    selected_ids = {stop["station_id"] for stop in plan["charging_stops"]}
    assert set(explanation["selected_station_reasons"]).issubset(selected_ids)
    allowed_entities = selected_ids | set(explanation["rejected_station_reasons"]) | {plan["plan_id"]}
    assert {reference["entity_id"] for reference in explanation["references"]}.issubset(allowed_entities)


@pytest.mark.asyncio
async def test_f2_infeasible_result_never_enters_confirmable_plan_history(client):
    trip_id = await _create_trip(client, soc=10)
    result = await client.post(
        f"/api/v1/trips/{trip_id}/plans",
        headers={"X-User-Id": OWNER},
    )
    assert result.status_code == 200
    assert result.json()["outcome"] == "PROVEN_INFEASIBLE"

    history = await client.get(
        f"/api/v1/trips/{trip_id}/plans",
        headers={"X-User-Id": OWNER},
    )
    assert history.status_code == 200
    assert history.json()["plans"] == []


@pytest.mark.asyncio
async def test_f2_plan_history_is_private_to_trip_owner(client):
    trip_id = await _create_trip(client)
    await _create_plan(client, trip_id)

    response = await client.get(
        f"/api/v1/trips/{trip_id}/plans",
        headers={"X-User-Id": OTHER_USER},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_f2_replanning_appends_version_without_mutating_version_one(client):
    trip_id = await _create_trip(client)
    first = await _create_plan(client, trip_id)
    first_snapshot = dict(first)

    second = await _create_plan(client, trip_id)
    history = await client.get(
        f"/api/v1/trips/{trip_id}/plans",
        headers={"X-User-Id": OWNER},
    )

    assert history.status_code == 200
    plans = history.json()["plans"]
    assert [plan["version"] for plan in plans] == [1, 2]
    assert plans[0] == first_snapshot
    assert second["plan_id"] != first["plan_id"]
    summaries = history.json()["history"]
    assert [item["version"] for item in summaries] == [1, 2]
    assert summaries[0]["total_distance_km"] == first["route"]["distance_km"]
    assert summaries[0]["stop_count"] == len(first["charging_stops"])
    assert summaries[1]["trigger_reason"] == "REPLAN"

    detail = await client.get(
        f"/api/v1/plans/{first['plan_id']}", headers={"X-User-Id": OWNER}
    )
    assert detail.status_code == 200
    assert detail.json()["plan"] == first_snapshot


@pytest.mark.asyncio
async def test_f2_owner_can_confirm_pending_plan_atomically(client):
    trip_id = await _create_trip(client)
    plan = await _create_plan(client, trip_id)

    response = await client.post(
        f"/api/v1/plans/{plan['plan_id']}/confirm",
        headers={"X-User-Id": OWNER, "If-Match": str(plan["version"])},
    )

    assert response.status_code == 200
    assert response.json()["plan"]["status"] == "CONFIRMED"
    assert response.json()["trip"]["status"] == "ACTIVE"
    assert response.json()["trip"]["confirmed_plan_version"] == plan["version"]


@pytest.mark.asyncio
async def test_confirmed_plan_appears_in_owner_trip_history_with_route_and_station_soc(client):
    trip_id = await _create_trip(client)
    plan = await _create_plan(client, trip_id)
    confirmed = await client.post(
        f"/api/v1/plans/{plan['plan_id']}/confirm",
        headers={"X-User-Id": OWNER, "If-Match": str(plan["version"])},
    )
    assert confirmed.status_code == 200

    response = await client.get("/api/v1/trips/history", headers={"X-User-Id": OWNER})

    assert response.status_code == 200
    history = response.json()["trips"]
    assert len(history) == 1
    item = history[0]
    assert item["trip_id"] == trip_id
    assert item["origin"]["address"]
    assert item["destination"]["address"]
    assert item["initial_soc"]["value_percent"] == 90
    assert item["selected_plan"]["status"] == "CONFIRMED"
    for stop in item["selected_plan"]["charging_stops"]:
        assert "arrival_soc_percent" in stop
        assert "departure_soc_percent" in stop


@pytest.mark.asyncio
async def test_pending_plan_does_not_appear_in_trip_history(client):
    trip_id = await _create_trip(client)
    await _create_plan(client, trip_id)

    response = await client.get("/api/v1/trips/history", headers={"X-User-Id": OWNER})

    assert response.status_code == 200
    assert response.json()["trips"] == []


@pytest.mark.asyncio
async def test_f2_reject_requires_reason_and_does_not_activate_trip(client):
    trip_id = await _create_trip(client)
    plan = await _create_plan(client, trip_id)

    response = await client.post(
        f"/api/v1/plans/{plan['plan_id']}/reject",
        json={"reason": "Detour is too long for this trip."},
        headers={"X-User-Id": OWNER, "If-Match": str(plan["version"])},
    )

    assert response.status_code == 200
    assert response.json()["plan"]["status"] == "REJECTED"
    assert response.json()["trip"]["status"] != "ACTIVE"


@pytest.mark.asyncio
async def test_f2_non_owner_cannot_confirm_and_state_remains_pending(client):
    trip_id = await _create_trip(client)
    plan = await _create_plan(client, trip_id)

    response = await client.post(
        f"/api/v1/plans/{plan['plan_id']}/confirm",
        headers={"X-User-Id": OTHER_USER, "If-Match": str(plan["version"])},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] in {"FORBIDDEN", "UNAUTHORIZED_ACTION"}

    history = await client.get(
        f"/api/v1/trips/{trip_id}/plans",
        headers={"X-User-Id": OWNER},
    )
    assert history.json()["plans"][0]["status"] == "PENDING"


@pytest.mark.asyncio
async def test_f2_stale_if_match_returns_409_without_state_change(client):
    trip_id = await _create_trip(client)
    plan = await _create_plan(client, trip_id)

    response = await client.post(
        f"/api/v1/plans/{plan['plan_id']}/confirm",
        headers={"X-User-Id": OWNER, "If-Match": "0"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "VERSION_CONFLICT"

    history = await client.get(
        f"/api/v1/trips/{trip_id}/plans",
        headers={"X-User-Id": OWNER},
    )
    assert history.json()["plans"][0]["status"] == "PENDING"


@pytest.mark.asyncio
async def test_f2_concurrent_double_confirm_has_exactly_one_winner(client):
    trip_id = await _create_trip(client)
    plan = await _create_plan(client, trip_id)
    url = f"/api/v1/plans/{plan['plan_id']}/confirm"
    headers = {"X-User-Id": OWNER, "If-Match": str(plan["version"])}

    first, second = await asyncio.gather(
        client.post(url, headers=headers),
        client.post(url, headers=headers),
    )

    assert sorted([first.status_code, second.status_code]) == [200, 409]
    conflict = first if first.status_code == 409 else second
    assert conflict.json()["error"]["code"] == "VERSION_CONFLICT"


@pytest.mark.asyncio
async def test_f2_confirming_old_pending_version_is_rejected_after_replan(client):
    trip_id = await _create_trip(client)
    first = await _create_plan(client, trip_id)
    await _create_plan(client, trip_id)

    response = await client.post(
        f"/api/v1/plans/{first['plan_id']}/confirm",
        headers={"X-User-Id": OWNER, "If-Match": str(first["version"])},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "VERSION_CONFLICT"


@pytest.mark.asyncio
async def test_f2_reject_preserves_existing_confirmed_plan(client):
    trip_id = await _create_trip(client)
    first = await _create_plan(client, trip_id)
    confirmed = await client.post(
        f"/api/v1/plans/{first['plan_id']}/confirm",
        headers={"X-User-Id": OWNER, "If-Match": str(first["version"])},
    )
    assert confirmed.status_code == 200

    second = await _create_plan(client, trip_id)
    rejected = await client.post(
        f"/api/v1/plans/{second['plan_id']}/reject",
        json={"reason": "Đường vòng không phù hợp."},
        headers={"X-User-Id": OWNER, "If-Match": str(second["version"])},
    )
    assert rejected.status_code == 200
    assert rejected.json()["trip"]["status"] == "ACTIVE"
    assert rejected.json()["trip"]["confirmed_plan_version"] == 1
    assert rejected.json()["plan"]["decision_reason"] == "Đường vòng không phù hợp."

    history = await client.get(f"/api/v1/trips/{trip_id}/plans", headers={"X-User-Id": OWNER})
    assert [item["status"] for item in history.json()["plans"]] == ["CONFIRMED", "REJECTED"]
    assert history.json()["history"][1]["decision_reason"] == "Đường vòng không phù hợp."
