import pytest


@pytest.mark.asyncio
async def test_create_trip_success(client):
    response = await client.post(
        "/api/v1/trips",
        json={
            "origin": {"address": "Ha Noi", "lat": None, "lng": None, "source_type": "MANUAL"},
            "destination": {"address": "Vinh", "lat": None, "lng": None, "source_type": "MANUAL"},
            "initial_soc_percent": 80,
            "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1",
            "preference": "balanced",
        },
        headers={"X-User-Id": "owner-1"},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "DRAFT"
    assert data["assumptions"]["reserve_soc_percent"] == 15.0
    assert data["assumptions"]["ambient_temperature_c"] == 25.0
    assert data["assumptions"]["vehicle_payload_kg"] == 150.0
    assert data["assumptions"]["vehicle_profile_version"] == "xe_x_v1.0"
    assert data["assumptions"]["source"] == "POLICY_CONFIG"
    assert data["assumptions"]["created_at"]
    assert response.headers["X-Trace-Id"]


@pytest.mark.asyncio
async def test_create_trip_rejects_same_origin_and_destination(client):
    response = await client.post(
        "/api/v1/trips",
        json={
            "origin": {
                "address": "Cùng một địa điểm",
                "lat": 21.005,
                "lng": 105.843,
                "source_type": "REAL_API",
            },
            "destination": {
                "address": "Cùng một địa điểm",
                "lat": 21.005,
                "lng": 105.843,
                "source_type": "REAL_API",
            },
            "initial_soc_percent": 60,
            "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1",
            "preference": "balanced",
        },
        headers={"X-User-Id": "owner-same-location"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["details"]["reason"] == "SAME_ORIGIN_DESTINATION"


@pytest.mark.asyncio
async def test_get_current_assumptions_returns_versioned_policy_snapshot(client):
    response = await client.get(
        "/api/v1/config/assumptions",
        params={"vehicle_profile_id": "xe-x-mvp-v1"},
    )

    assert response.status_code == 200
    data = response.json()
    assert {key: data[key] for key in (
        "policy_version",
        "reserve_soc_percent",
        "ambient_temperature_c",
        "vehicle_payload_kg",
        "vehicle_profile_version",
        "source",
        "created_at",
    )} == {
        "policy_version": "pilot-policy-v1",
        "reserve_soc_percent": 15.0,
        "ambient_temperature_c": 25.0,
        "vehicle_payload_kg": 150.0,
        "vehicle_profile_version": "xe_x_v1.0",
        "source": "POLICY_CONFIG",
        "created_at": data["created_at"],
    }
    assert data["vehicle_profile"]["id"] == "xe-x-mvp-v1"
    assert data["vehicle_profile"]["battery_capacity_kwh"] == 75.0
    assert data["vehicle_profile"]["connector_type"] == "CCS2"


@pytest.mark.asyncio
async def test_vf6_profile_exposes_planning_and_official_vehicle_specs(client):
    response = await client.get(
        "/api/v1/config/assumptions",
        params={"vehicle_profile_id": "vinfast-vf6-plus-v1"},
    )

    assert response.status_code == 200
    profile = response.json()["vehicle_profile"]
    assert profile["name"] == "VinFast VF 6 Plus"
    assert profile["usable_capacity_kwh"] == 59.6
    assert profile["reference_range_km"] == 381.0
    assert profile["reference_range_standard"] == "WLTP"
    assert profile["brochure_range_km"] == 460.0
    assert profile["brochure_range_standard"] == "NEDC"
    assert profile["motor_power_kw"] == 150.0
    assert profile["max_torque_nm"] == 310.0
    assert profile["connector_type"] == "CCS2"
    assert profile["official_source_url"].startswith("https://vinfastauto.com/")


@pytest.mark.asyncio
async def test_create_trip_supports_vietnamese_diacritics(client):
    response = await client.post(
        "/api/v1/trips",
        json={
            "origin": {"address": "Hà Nội", "lat": None, "lng": None, "source_type": "MANUAL"},
            "destination": {"address": "Hòa Bình", "lat": None, "lng": None, "source_type": "MANUAL"},
            "initial_soc_percent": 55,
            "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1",
            "preference": "balanced",
        },
        headers={"X-User-Id": "owner-vn"},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "DRAFT"


@pytest.mark.asyncio
async def test_create_trip_accepts_google_place_label_with_coordinates(client):
    response = await client.post(
        "/api/v1/trips",
        json={
            "origin": {
                "address": "Hà Nội, Việt Nam",
                "lat": 21.0278,
                "lng": 105.8342,
                "source_type": "REAL_API",
            },
            "destination": {
                "address": "Thành phố Vinh, Nghệ An, Việt Nam",
                "lat": 18.6796,
                "lng": 105.6813,
                "source_type": "REAL_API",
            },
            "initial_soc_percent": 60,
            "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1",
            "preference": "balanced",
        },
        headers={"X-User-Id": "owner-google-place"},
    )

    assert response.status_code == 201
    trip = await client.get(
        f"/api/v1/trips/{response.json()['trip_id']}",
        headers={"X-User-Id": "owner-google-place"},
    )
    assert trip.json()["origin"] == {
        "address": "Hà Nội, Việt Nam",
        "lat": 21.0278,
        "lng": 105.8342,
        "source_type": "REAL_API",
    }


@pytest.mark.asyncio
async def test_create_trip_rejects_invalid_soc(client):
    response = await client.post(
        "/api/v1/trips",
        json={
            "origin": {"address": "Ha Noi", "lat": None, "lng": None, "source_type": "MANUAL"},
            "destination": {"address": "Vinh", "lat": None, "lng": None, "source_type": "MANUAL"},
            "initial_soc_percent": 0,
            "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1",
            "preference": "balanced",
        },
    )

    assert response.status_code == 400
    data = response.json()
    assert data["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_create_trip_rejects_missing_soc_at_api_boundary(client):
    response = await client.post(
        "/api/v1/trips",
        json={
            "origin": {"address": "Ha Noi", "lat": None, "lng": None, "source_type": "MANUAL"},
            "destination": {"address": "Vinh", "lat": None, "lng": None, "source_type": "MANUAL"},
            "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1",
            "preference": "balanced",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_create_trip_returns_ambiguous_location(client):
    response = await client.post(
        "/api/v1/trips",
        json={
            "origin": {"address": "Hoang Mai", "lat": None, "lng": None, "source_type": "MANUAL"},
            "destination": {"address": "Vinh", "lat": None, "lng": None, "source_type": "MANUAL"},
            "initial_soc_percent": 70,
            "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1",
            "preference": "balanced",
        },
    )

    assert response.status_code == 409
    data = response.json()
    assert data["error"]["code"] == "AMBIGUOUS_LOCATION"
    assert len(data["error"]["details"]["candidates"]) >= 2


@pytest.mark.asyncio
async def test_get_trip_returns_saved_trip(client):
    create_response = await client.post(
        "/api/v1/trips",
        json={
            "origin": {"address": "Ha Noi", "lat": None, "lng": None, "source_type": "MANUAL"},
            "destination": {"address": "Da Nang", "lat": None, "lng": None, "source_type": "MANUAL"},
            "initial_soc_percent": 65,
            "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1",
            "preference": "balanced",
        },
        headers={"X-User-Id": "owner-2"},
    )
    trip_id = create_response.json()["trip_id"]

    response = await client.get(f"/api/v1/trips/{trip_id}", headers={"X-User-Id": "owner-2"})

    assert response.status_code == 200
    data = response.json()
    assert data["trip_id"] == trip_id
    assert data["owner_id"] == "owner-2"
