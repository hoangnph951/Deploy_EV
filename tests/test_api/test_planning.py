import pytest

from src.packages.agent.planning.nodes.planning_nodes import (
    configure_planning_providers,
    set_routing_provider,
)
from src.packages.core.trips.infrastructure.environment import StaticEnvironmentProvider
from src.packages.core.trips.infrastructure.routing import (
    InMemoryRoutingProvider,
    RoutingUnavailableError,
)
from src.packages.core.trips.infrastructure.station_service import (
    FixtureStationDataService,
    StationProviderError,
)


class FailingRoutingProvider:
    def get_route(self, *args, **kwargs):
        raise RoutingUnavailableError("simulated provider failure")


class EndpointNotFoundRoutingProvider:
    def get_route(self, *args, **kwargs):
        raise RoutingUnavailableError(
            "simulated endpoint failure",
            http_status=400,
            provider_status="NOT_FOUND",
            retryable=False,
        )


class FailingStationService:
    def find_corridor_stations(self, *args, **kwargs):
        raise StationProviderError("simulated station provider failure")

    def find_station_window(self, *args, **kwargs):
        raise StationProviderError("simulated station provider failure")


class FallbackEnvironmentProvider(StaticEnvironmentProvider):
    def get_snapshot(self, polyline, *, fallback_temperature_c=None):
        snapshot = super().get_snapshot(
            polyline, fallback_temperature_c=fallback_temperature_c
        )
        return snapshot.model_copy(
            update={
                "status": "POLICY_FALLBACK",
                "is_degraded": True,
                "consumption_margin_percent": 20.0,
                "warning": "Open-Meteo unavailable in test.",
            }
        )


@pytest.mark.asyncio
async def test_generate_trip_plan_happy_path(client):
    # 1. Create a trip from Hanoi to Vinh with 90% SOC
    create_res = await client.post(
        "/api/v1/trips",
        json={
            "origin": {"address": "Ha Noi", "lat": None, "lng": None, "source_type": "MANUAL"},
            "destination": {"address": "Vinh", "lat": None, "lng": None, "source_type": "MANUAL"},
            "initial_soc_percent": 90,
            "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1",
            "preference": "balanced",
        },
        headers={"X-User-Id": "owner-1"},
    )
    assert create_res.status_code == 201
    trip_id = create_res.json()["trip_id"]

    # 2. Trigger planning
    plan_res = await client.post(
        f"/api/v1/trips/{trip_id}/plans",
        headers={"X-User-Id": "owner-1"},
    )
    assert plan_res.status_code == 201
    assert plan_res.json()["outcome"] == "PLAN_CREATED"
    plan_data = plan_res.json()["plan"]

    assert plan_data["trip_id"] == trip_id
    assert plan_data["status"] == "PENDING"
    assert plan_data["version"] == 1
    assert plan_data["route"]["distance_km"] > 100
    assert len(plan_data["route"]["polyline"]) > 0
    assert plan_data["risk_assessment"]["is_feasible"] is True
    assert plan_data["risk_assessment"]["level"] in [
        "LOW_RISK",
        "MEDIUM_RISK",
        "HIGH_RISK",
    ]
    assert plan_data["assumptions"]["reserve_soc_percent"] == 15.0
    assert plan_data["soc_points"][0]["kind"] == "ORIGIN"
    assert plan_data["soc_points"][-1]["kind"] == "DESTINATION"
    assert plan_data["effective_consumption_wh_per_km"] > 0
    assert plan_data["environment"]["weather_provenance"]["source"] == "TEST_FIXTURE"
    assert plan_data["route"]["provider"] == "TEST_FIXTURE"
    assert 1 <= len(plan_res.json()["alternatives"]) <= 3
    detail_res = await client.get(
        f"/api/v1/trips/{trip_id}", headers={"X-User-Id": "owner-1"}
    )
    assert detail_res.json()["status"] == "PLANNED"


@pytest.mark.asyncio
async def test_short_safe_trip_does_not_require_station_provider(client):
    create_res = await client.post(
        "/api/v1/trips",
        json={
            "origin": {
                "address": "Điểm A",
                "lat": 21.000,
                "lng": 105.840,
                "source_type": "REAL_API",
            },
            "destination": {
                "address": "Điểm B",
                "lat": 21.010,
                "lng": 105.850,
                "source_type": "REAL_API",
            },
            "initial_soc_percent": 60,
            "soc_source_type": "MANUAL",
            "vehicle_profile_id": "vinfast-vf6-plus-v1",
            "preference": "balanced",
        },
        headers={"X-User-Id": "owner-direct-without-locator"},
    )
    assert create_res.status_code == 201

    configure_planning_providers(
        routing_provider=InMemoryRoutingProvider(),
        station_service=FailingStationService(),
        environment_provider=StaticEnvironmentProvider(),
    )
    try:
        plan_res = await client.post(
            f"/api/v1/trips/{create_res.json()['trip_id']}/plans",
            headers={"X-User-Id": "owner-direct-without-locator"},
        )
    finally:
        configure_planning_providers(
            routing_provider=InMemoryRoutingProvider(),
            station_service=FixtureStationDataService(),
            environment_provider=StaticEnvironmentProvider(),
        )

    assert plan_res.status_code == 201
    assert plan_res.json()["outcome"] == "PLAN_CREATED"
    assert plan_res.json()["plan"]["charging_stops"] == []


@pytest.mark.asyncio
async def test_environment_fallback_returns_conditional_plan(client):
    create_res = await client.post(
        "/api/v1/trips",
        json={
            "origin": {
                "address": "Điểm A",
                "lat": 21.000,
                "lng": 105.840,
                "source_type": "REAL_API",
            },
            "destination": {
                "address": "Điểm B",
                "lat": 21.010,
                "lng": 105.850,
                "source_type": "REAL_API",
            },
            "initial_soc_percent": 60,
            "soc_source_type": "MANUAL",
            "vehicle_profile_id": "vinfast-vf6-plus-v1",
            "preference": "balanced",
        },
        headers={"X-User-Id": "owner-environment-fallback"},
    )
    assert create_res.status_code == 201

    configure_planning_providers(
        routing_provider=InMemoryRoutingProvider(),
        station_service=FixtureStationDataService(),
        environment_provider=FallbackEnvironmentProvider(),
    )
    try:
        plan_res = await client.post(
            f"/api/v1/trips/{create_res.json()['trip_id']}/plans",
            headers={"X-User-Id": "owner-environment-fallback"},
        )
    finally:
        configure_planning_providers(
            routing_provider=InMemoryRoutingProvider(),
            station_service=FixtureStationDataService(),
            environment_provider=StaticEnvironmentProvider(),
        )

    assert plan_res.status_code == 200
    payload = plan_res.json()
    assert payload["outcome"] == "CONDITIONAL"
    assert payload["plan"]["environment"]["status"] == "POLICY_FALLBACK"
    assert payload["plan"]["environment"]["consumption_margin_percent"] == 20.0
    assert "ENVIRONMENT_DATA_FALLBACK" in payload["plan"]["risk_assessment"][
        "reason_codes"
    ]


@pytest.mark.asyncio
async def test_generate_trip_plan_infeasible_low_soc(client):
    # Trip with initial SOC 10% (under 15% reserve)
    create_res = await client.post(
        "/api/v1/trips",
        json={
            "origin": {"address": "Ha Noi", "lat": None, "lng": None, "source_type": "MANUAL"},
            "destination": {"address": "Vinh", "lat": None, "lng": None, "source_type": "MANUAL"},
            "initial_soc_percent": 10,
            "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1",
            "preference": "balanced",
        },
        headers={"X-User-Id": "owner-2"},
    )
    assert create_res.status_code == 201
    trip_id = create_res.json()["trip_id"]

    plan_res = await client.post(
        f"/api/v1/trips/{trip_id}/plans",
        headers={"X-User-Id": "owner-2"},
    )
    assert plan_res.status_code == 200
    outcome = plan_res.json()

    assert outcome["outcome"] == "PROVEN_INFEASIBLE"
    assert outcome["charging_stops"] == []
    assert outcome["risk_assessment"]["is_feasible"] is False
    assert outcome["risk_assessment"]["verdict"] == "INFEASIBLE"
    assert "INITIAL_SOC_BELOW_RESERVE" in outcome["risk_assessment"]["reason_codes"]

    list_res = await client.get(
        f"/api/v1/trips/{trip_id}/plans",
        headers={"X-User-Id": "owner-2"},
    )
    assert list_res.status_code == 200
    assert list_res.json()["plans"] == []


@pytest.mark.asyncio
async def test_station_data_outage_is_action_required_not_infeasible(client):
    create_res = await client.post(
        "/api/v1/trips",
        json={
            "origin": {
                "address": "Ha Noi",
                "lat": 21.03,
                "lng": 105.85,
                "source_type": "MANUAL",
            },
            "destination": {
                "address": "Da Nang",
                "lat": 16.05,
                "lng": 108.20,
                "source_type": "MANUAL",
            },
            "initial_soc_percent": 50,
            "soc_source_type": "MANUAL",
            "vehicle_profile_id": "vinfast-vf3-v1",
            "preference": "balanced",
        },
        headers={"X-User-Id": "owner-station-outage"},
    )
    assert create_res.status_code == 201

    configure_planning_providers(
        routing_provider=InMemoryRoutingProvider(),
        station_service=FailingStationService(),
        environment_provider=StaticEnvironmentProvider(),
    )
    try:
        plan_res = await client.post(
            f"/api/v1/trips/{create_res.json()['trip_id']}/plans",
            headers={"X-User-Id": "owner-station-outage"},
        )
    finally:
        configure_planning_providers(
            routing_provider=InMemoryRoutingProvider(),
            station_service=FixtureStationDataService(),
            environment_provider=StaticEnvironmentProvider(),
        )

    assert plan_res.status_code == 200
    assert plan_res.json()["outcome"] == "ACTION_REQUIRED"
    assert plan_res.json()["failure_category"] == "STATION_DATA"


@pytest.mark.asyncio
async def test_list_trip_plans_retrieval(client):
    create_res = await client.post(
        "/api/v1/trips",
        json={
            "origin": {"address": "Ha Noi", "lat": None, "lng": None, "source_type": "MANUAL"},
            "destination": {"address": "Hoa Binh", "lat": None, "lng": None, "source_type": "MANUAL"},
            "initial_soc_percent": 85,
            "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1",
            "preference": "balanced",
        },
        headers={"X-User-Id": "owner-3"},
    )
    trip_id = create_res.json()["trip_id"]

    await client.post(
        f"/api/v1/trips/{trip_id}/plans",
        headers={"X-User-Id": "owner-3"},
    )

    list_res = await client.get(
        f"/api/v1/trips/{trip_id}/plans",
        headers={"X-User-Id": "owner-3"},
    )
    assert list_res.status_code == 200
    plans = list_res.json()["plans"]
    assert len(plans) >= 1
    assert plans[0]["trip_id"] == trip_id


@pytest.mark.asyncio
async def test_planning_forbidden_for_other_user(client):
    create_res = await client.post(
        "/api/v1/trips",
        json={
            "origin": {"address": "Ha Noi", "lat": None, "lng": None, "source_type": "MANUAL"},
            "destination": {"address": "Vinh", "lat": None, "lng": None, "source_type": "MANUAL"},
            "initial_soc_percent": 80,
            "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1",
            "preference": "balanced",
        },
        headers={"X-User-Id": "owner-real"},
    )
    trip_id = create_res.json()["trip_id"]

    plan_res = await client.post(
        f"/api/v1/trips/{trip_id}/plans",
        headers={"X-User-Id": "owner-imposter"},
    )
    assert plan_res.status_code == 403


@pytest.mark.asyncio
async def test_routing_failure_returns_provider_error(client):
    create_res = await client.post(
        "/api/v1/trips",
        json={
            "origin": {"address": "Ha Noi", "lat": None, "lng": None, "source_type": "MANUAL"},
            "destination": {"address": "Vinh", "lat": None, "lng": None, "source_type": "MANUAL"},
            "initial_soc_percent": 90,
            "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1",
            "preference": "balanced",
        },
        headers={"X-User-Id": "owner-routing-failure"},
    )
    trip_id = create_res.json()["trip_id"]

    set_routing_provider(FailingRoutingProvider())
    try:
        plan_res = await client.post(
            f"/api/v1/trips/{trip_id}/plans",
            headers={"X-User-Id": "owner-routing-failure"},
        )
    finally:
        set_routing_provider(InMemoryRoutingProvider())

    assert plan_res.status_code == 503
    assert plan_res.json()["error"]["code"] == "ROUTING_UNAVAILABLE"
    detail_res = await client.get(
        f"/api/v1/trips/{trip_id}",
        headers={"X-User-Id": "owner-routing-failure"},
    )
    assert detail_res.json()["status"] == "PLANNING_FAILED"


@pytest.mark.asyncio
async def test_endpoint_not_found_returns_action_required_instead_of_503(client):
    create_res = await client.post(
        "/api/v1/trips",
        json={
            "origin": {"address": "Ha Noi", "lat": None, "lng": None, "source_type": "MANUAL"},
            "destination": {"address": "Vinh", "lat": None, "lng": None, "source_type": "MANUAL"},
            "initial_soc_percent": 52,
            "soc_source_type": "MANUAL",
            "vehicle_profile_id": "xe-x-mvp-v1",
            "preference": "balanced",
        },
        headers={"X-User-Id": "owner-endpoint-failure"},
    )

    set_routing_provider(EndpointNotFoundRoutingProvider())
    try:
        plan_res = await client.post(
            f"/api/v1/trips/{create_res.json()['trip_id']}/plans",
            headers={"X-User-Id": "owner-endpoint-failure"},
        )
    finally:
        set_routing_provider(InMemoryRoutingProvider())

    assert plan_res.status_code == 200
    payload = plan_res.json()
    assert payload["outcome"] == "ACTION_REQUIRED"
    assert payload["provider_status"] == "NOT_FOUND"
    assert payload["recovery_options"]
