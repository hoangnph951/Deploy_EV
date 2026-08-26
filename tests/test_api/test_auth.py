import pytest

from src.apps.api.bootstrap.config import Settings, get_settings
from src.apps.api.main import app


def registration_payload(email: str = "minh@example.com") -> dict:
    return {
        "full_name": "Nguyễn Văn Minh",
        "email": email,
        "phone": "0912 345 678",
        "password": "Matkhau123",
        "password_confirmation": "Matkhau123",
        "accepted_terms": True,
    }


@pytest.mark.asyncio
async def test_register_login_session_and_logout(client):
    register = await client.post("/api/v1/auth/register", json=registration_payload())

    assert register.status_code == 201
    auth = register.json()
    assert auth["token_type"] == "bearer"
    assert auth["user"]["email"] == "minh@example.com"
    assert auth["needs_vehicle_setup"] is True
    token = auth["access_token"]

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["full_name"] == "Nguyễn Văn Minh"

    await client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    expired = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert expired.status_code == 401
    assert expired.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.asyncio
async def test_duplicate_email_and_invalid_password_are_rejected(client):
    first = await client.post("/api/v1/auth/register", json=registration_payload())
    duplicate = await client.post("/api/v1/auth/register", json=registration_payload("MINH@example.com"))
    bad_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "minh@example.com", "password": "sai-mat-khau", "remember_me": False},
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "EMAIL_ALREADY_EXISTS"
    assert bad_login.status_code == 401
    assert bad_login.json()["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_user_adds_verified_vehicle_and_it_becomes_default(client):
    register = await client.post("/api/v1/auth/register", json=registration_payload())
    token = register.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    profiles = await client.get("/api/v1/vehicle-profiles")
    assert profiles.status_code == 200
    profile_ids = {item["id"] for item in profiles.json()["profiles"]}
    assert profile_ids == {
        "vinfast-vf3-v1",
        "vinfast-vf5-plus-v1",
        "vinfast-vf6-eco-v1",
        "vinfast-vf6-plus-v1",
        "vinfast-vf7-eco-v1",
        "vinfast-vf7-plus-awd-v1",
        "vinfast-vf8-eco-catl-v1",
        "vinfast-vf8-plus-catl-v1",
    }
    assert all(item["official_source_url"] for item in profiles.json()["profiles"])

    created = await client.post(
        "/api/v1/me/vehicles",
        headers=headers,
        json={
            "vehicle_profile_id": "vinfast-vf6-plus-v1",
            "nickname": "VF 6 của Minh",
            "license_plate": "30a-123.45",
            "make_default": True,
        },
    )
    assert created.status_code == 201
    vehicle = created.json()
    assert vehicle["is_default"] is True
    assert vehicle["license_plate"] == "30A-123.45"
    assert vehicle["vehicle_profile"]["connector_type"] == "CCS2"
    assert vehicle["vehicle_profile"]["usable_capacity_kwh"] == 59.6

    listed = await client.get("/api/v1/me/vehicles", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["vehicles"][0]["id"] == vehicle["id"]


@pytest.mark.asyncio
async def test_registration_requires_matching_strong_password_and_terms(client):
    payload = registration_payload()
    payload.update(
        {
            "password": "weakpass",
            "password_confirmation": "different",
            "accepted_terms": False,
        }
    )
    response = await client.post("/api/v1/auth/register", json=payload)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_production_trip_requires_a_vehicle_owned_by_the_authenticated_user(client):
    register = await client.post("/api/v1/auth/register", json=registration_payload())
    token = register.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    await client.post(
        "/api/v1/me/vehicles",
        headers=headers,
        json={"vehicle_profile_id": "vinfast-vf6-plus-v1", "make_default": True},
    )
    app.dependency_overrides[get_settings] = lambda: Settings(app_env="development")
    try:
        accepted = await client.post(
            "/api/v1/trips",
            headers=headers,
            json={
                "origin": {"address": "Hà Nội", "lat": 21.0285, "lng": 105.8542, "source_type": "REAL_API"},
                "destination": {"address": "Vinh", "lat": 18.6796, "lng": 105.6813, "source_type": "REAL_API"},
                "initial_soc_percent": 80,
                "vehicle_profile_id": "vinfast-vf6-plus-v1",
            },
        )
        rejected = await client.post(
            "/api/v1/trips",
            headers=headers,
            json={
                "origin": {"address": "Hà Nội", "lat": 21.0285, "lng": 105.8542, "source_type": "REAL_API"},
                "destination": {"address": "Vinh", "lat": 18.6796, "lng": 105.6813, "source_type": "REAL_API"},
                "initial_soc_percent": 80,
                "vehicle_profile_id": "xe-x-mvp-v1",
            },
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert accepted.status_code == 201
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "VEHICLE_NOT_REGISTERED"
