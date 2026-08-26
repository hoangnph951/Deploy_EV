from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Lock

import httpx
import pytest

from src.packages.core.trips.infrastructure.fixtures.station_fixtures import (
    StationSnapshotFixture,
)
from src.packages.core.trips.infrastructure.station_service import (
    FixtureStationDataService,
    StationProviderError,
    VinFastStationDataService,
)


def test_fixture_longitude_bounding_box_accounts_for_latitude() -> None:
    station = StationSnapshotFixture(
        id="high-latitude",
        name="High latitude CCS2",
        lat=60.1,
        lon=10.15,
        address="Test corridor",
        connector_types=["CCS2"],
        max_power_kw=60.0,
        source="TEST_FIXTURE",
        snapshot_timestamp=datetime.now(UTC).isoformat(),
        status="OPERATIONAL",
    )
    service = FixtureStationDataService(fixtures=[station])

    candidates = service.find_corridor_stations(
        polyline=[[60.0, 10.0], [60.1, 10.0], [60.2, 10.0]],
        origin_lat=60.0,
        origin_lng=10.0,
        dest_lat=60.2,
        dest_lng=10.0,
        max_corridor_buffer_km=10.0,
        max_detour_min=30.0,
    )

    assert [candidate.station_id for candidate in candidates] == ["high-latitude"]


def test_vinfast_detail_maps_verified_connector_power_and_status() -> None:
    service = VinFastStationDataService()
    service._generation = "439"
    service._dataset_retrieved_at = datetime.now(UTC)
    summary = {
        "entity_id": "32504",
        "station_id": "C.HNO0862",
        "name": "Nhượng quyền Tư Nhân Đỗ Văn Vui",
        "address": "Thôn Lê Xá",
        "lat": 21.084015,
        "lon": 105.878189,
        "status": "ACTIVE",
        "parking_fee": True,
        "distance_from_origin_km": 42.0,
        "detour_distance_km": 1.2,
        "detour_duration_min": 1.8,
    }
    detail = {
        "charging_status": "ACTIVE",
        "data": {
            "id": "C.HNO0862",
            "name": summary["name"],
            "address": summary["address"],
            "access_type": "Public",
            "opening_times": {"twentyfourseven": True},
            "last_updated": "2026-06-30T14:44:56.751Z",
            "evses": [
                {
                    "connectors": [
                        {
                            "standard": "IEC_62196_T2_COMBO",
                            "max_electric_power": 60000,
                            "last_updated": "2026-06-30T14:44:56.751Z",
                        }
                    ]
                },
                {
                    "connectors": [
                        {
                            "standard": "IEC_62196_T2_COMBO",
                            "max_electric_power": 60000,
                            "last_updated": "2026-06-30T14:44:56.751Z",
                        }
                    ]
                },
            ],
            "extra_data": {"depot_status": "Active", "parking_fee": False},
        },
    }

    candidate = service._parse_detail(summary, detail, "CCS2")

    assert candidate is not None
    assert candidate.station_id == "C.HNO0862"
    assert candidate.connector_types == ["CCS2"]
    assert candidate.connector_standard == "IEC_62196_T2_COMBO"
    assert candidate.max_power_kw == 60.0
    assert candidate.port_count == 2
    assert candidate.opening_24_7 is True
    assert candidate.parking_fee is True
    assert candidate.provenance is not None
    assert candidate.provenance.source == "VINFAST_OFFICIAL"


def test_vinfast_detail_rejects_maintenance_station() -> None:
    service = VinFastStationDataService()
    summary = {
        "entity_id": "32504",
        "station_id": "C.HNO0862",
        "name": "Station",
        "address": "Address",
        "lat": 21.0,
        "lon": 105.0,
        "status": "INACTIVE",
        "parking_fee": False,
        "distance_from_origin_km": 42.0,
        "detour_distance_km": 1.0,
        "detour_duration_min": 1.5,
    }
    detail = {
        "charging_status": "INACTIVE",
        "data": {
            "evses": [],
            "extra_data": {"depot_status": "Maintaining"},
        },
    }

    assert service._parse_detail(summary, detail, "CCS2") is None


def test_vinfast_detail_parser_accepts_unwrapped_fetch_response() -> None:
    """Regression: _fetch_one_detail returns the inner `data` object."""
    service = VinFastStationDataService()
    service._generation = "439"
    summary = {
        "entity_id": "32504",
        "station_id": "C.HNO0862",
        "name": "Station",
        "address": "Address",
        "lat": 21.0,
        "lon": 105.0,
        "status": "ACTIVE",
        "distance_from_origin_km": 42.0,
        "detour_distance_km": 1.0,
        "detour_duration_min": 1.5,
    }
    detail = {
        "id": "C.HNO0862",
        "name": "Station",
        "address": "Address",
        "charging_status": "ACTIVE",
        "evses": [{"connectors": [{"standard": "IEC_62196_T2_COMBO", "max_electric_power": 60000}]}],
        "extra_data": {"depot_status": "Active"},
    }

    candidate = service._parse_detail(summary, detail, "CCS2")

    assert candidate is not None
    assert candidate.station_id == "C.HNO0862"


def test_dense_short_route_uses_full_adaptive_detail_budget() -> None:
    service = VinFastStationDataService(max_detail_candidates=36)
    candidates = [
        {
            "entity_id": str(index),
            "status": "ACTIVE",
            "distance_to_route_km": (index % 9) / 10.0,
            "distance_from_origin_km": (index % 30) / 2.0,
        }
        for index in range(100)
    ]

    shortlisted = service._distribute_candidates_along_route(candidates)

    assert len(shortlisted) == 36
    assert any(item["distance_from_origin_km"] == 0.0 for item in shortlisted)
    assert len({item["entity_id"] for item in shortlisted}) == 36


def test_fetch_one_detail_raises_explicit_error_on_403_waf() -> None:
    class MockClient:
        def get(self, url, **kwargs):
            return httpx.Response(
                403, text="<html>::IM_UNDER_ATTACK_BOX::</html>", headers={"content-type": "text/html"}
            )

    service = VinFastStationDataService()
    with pytest.raises(StationProviderError, match="blocked by the upstream anti-bot/WAF layer"):
        service._fetch_one_detail("12345", client=MockClient())


def test_fetch_one_detail_raises_explicit_error_on_html_response() -> None:
    class MockClient:
        def get(self, url, **kwargs):
            return httpx.Response(
                200, text="<html><body>Challenge</body></html>", headers={"content-type": "text/html"}
            )

    service = VinFastStationDataService()
    with pytest.raises(StationProviderError, match="blocked by the upstream anti-bot/WAF layer"):
        service._fetch_one_detail("12345", client=MockClient())


def test_concurrent_detail_fetches_share_single_upstream_request(monkeypatch) -> None:
    service = VinFastStationDataService(min_request_interval_seconds=0)
    calls = 0
    calls_lock = Lock()

    class MockResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = '{"data": {}}'

        def json(self):
            return {"data": {"station": "detail"}}

    class MockClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, **kwargs):
            nonlocal calls
            if "/get-locator/" in url:
                with calls_lock:
                    calls += 1
            return MockResponse()

    monkeypatch.setattr(
        "src.packages.core.trips.infrastructure.station_service.httpx.Client",
        lambda **kwargs: MockClient(),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: service._fetch_details(["station-1"]), range(2)))

    assert calls == 1
    assert results == [{"station-1": {"station": "detail"}}] * 2
