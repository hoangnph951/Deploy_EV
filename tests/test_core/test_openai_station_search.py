from datetime import UTC, datetime

import pytest

from src.packages.core.trips.infrastructure.geocoding import GeocodeEntry
from src.packages.core.trips.infrastructure.openai_station_search import (
    OpenAIWebStationDataService,
    WebStationCandidate,
    WebStationSearchResult,
)
from src.packages.core.trips.infrastructure.station_service import (
    CandidateStation,
    FallbackStationDataService,
    StationProviderError,
    VinFastAccessDeniedError,
)

SOURCE_URL = "https://example.com/verified-station"


def test_station_chain_preserves_primary_access_denied() -> None:
    class Primary:
        def find_corridor_stations(self, **kwargs):
            raise VinFastAccessDeniedError()

    class Fallback:
        def find_corridor_stations(self, **kwargs):
            raise StationProviderError("fallback unavailable")

    service = FallbackStationDataService(primary=Primary(), fallback=Fallback())
    with pytest.raises(VinFastAccessDeniedError):
        service.find_corridor_stations(polyline=[], origin_lat=0, origin_lng=0, dest_lat=1, dest_lng=1)


class FakeResponse:
    def __init__(self, *, source_urls: list[str]):
        self.output_parsed = WebStationSearchResult(
            candidates=[
                WebStationCandidate(
                    name="Fallback CCS2 Station",
                    address="Test corridor, Viet Nam",
                    connector_type="CCS2",
                    max_power_kw=60.0,
                    port_count=2,
                    source_url=SOURCE_URL,
                    evidence="The source lists a public 60 kW CCS2 charging station.",
                )
            ]
        )
        self._source_urls = source_urls

    def model_dump(self):
        return {
            "output": [
                {
                    "type": "web_search_call",
                    "action": {
                        "sources": [{"url": source_url} for source_url in self._source_urls]
                    },
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": self.output_parsed.model_dump_json(),
                        }
                    ],
                },
            ]
        }


class FakeResponses:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.requests: list[dict] = []

    def parse(self, **kwargs):
        self.requests.append(kwargs)
        return self.response


class FakeOpenAI:
    def __init__(self, response: FakeResponse):
        self.responses = FakeResponses(response)


class FakeGeocoder:
    def resolve_text(self, query: str, field_name: str) -> GeocodeEntry:
        assert "Fallback CCS2 Station" in query
        assert field_name == "fallback_station"
        return GeocodeEntry(
            name="Fallback CCS2 Station",
            formatted_address="Test corridor, Viet Nam",
            lat=20.5,
            lng=105.8,
        )


class StaticStationService:
    def __init__(self, stations: list[CandidateStation] | None = None, *, fail: bool = False):
        self.stations = stations or []
        self.fail = fail
        self.calls = 0

    def find_corridor_stations(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise StationProviderError("provider unavailable")
        return self.stations


def _search_service(source_urls: list[str]) -> tuple[OpenAIWebStationDataService, FakeOpenAI]:
    client = FakeOpenAI(FakeResponse(source_urls=source_urls))
    service = OpenAIWebStationDataService(
        api_key="test-key",
        model="test-web-model",
        geocoder=FakeGeocoder(),
        client=client,
    )
    return service, client


def _find(service) -> list[CandidateStation]:
    return service.find_corridor_stations(
        polyline=[[21.0, 105.8], [20.5, 105.8], [20.0, 105.8]],
        origin_lat=21.0,
        origin_lng=105.8,
        dest_lat=20.0,
        dest_lng=105.8,
        max_corridor_buffer_km=5.0,
        max_detour_min=15.0,
        required_connector="CCS2",
        total_route_distance_km=100.0,
        origin_name="Ha Noi",
        dest_name="Thanh Hoa",
    )


def test_openai_web_station_requires_cited_source_and_geocodes_candidate() -> None:
    service, client = _search_service([SOURCE_URL])

    stations = _find(service)

    assert len(stations) == 1
    station = stations[0]
    assert station.distance_from_origin_km == pytest.approx(50.0)
    assert station.connector_types == ["CCS2"]
    assert station.max_power_kw == 60.0
    assert station.station_status == "UNVERIFIED"
    assert station.detail_quality == "UNVERIFIED"
    assert station.freshness == "STALE"
    assert station.provenance is not None
    assert station.provenance.source == "OPENAI_WEB_SEARCH"
    request = client.responses.requests[0]
    assert request["tools"][0]["type"] == "web_search"
    assert request["include"] == ["web_search_call.action.sources"]
    assert request["text_format"] is WebStationSearchResult


def test_openai_web_station_rejects_url_not_returned_by_web_search() -> None:
    service, _ = _search_service(["https://example.com/different-source"])

    assert _find(service) == []


def test_openai_authentication_failure_is_typed_for_operator_recovery() -> None:
    class UnauthorizedResponses:
        def parse(self, **kwargs):
            from openai import OpenAIError

            error = OpenAIError("invalid key")
            error.status_code = 401
            raise error

    class UnauthorizedClient:
        responses = UnauthorizedResponses()

    service = OpenAIWebStationDataService(
        api_key="bad-key",
        model="test-web-model",
        geocoder=FakeGeocoder(),
        client=UnauthorizedClient(),
    )
    with pytest.raises(StationProviderError) as captured:
        _find(service)
    assert captured.value.code == "OPENAI_AUTHENTICATION_FAILED"
    assert captured.value.http_status == 401


def test_openai_station_window_searches_reachable_slice_and_caches_result() -> None:
    service, client = _search_service([SOURCE_URL])
    polyline = [[21.0, 105.8], [20.5, 105.8], [20.0, 105.8], [19.5, 105.8]]
    kwargs = {
        "polyline": polyline,
        "origin_lat": 21.0,
        "origin_lng": 105.8,
        "dest_lat": 19.5,
        "dest_lng": 105.8,
        "progress_start_km": 30.0,
        "progress_end_km": 230.0,
        "compatible_connectors": ("CCS2",),
        "max_corridor_buffer_km": 5.0,
        "max_detour_min": 15.0,
        "total_route_distance_km": 300.0,
        "target_candidate_count": 8,
        "origin_name": "Ha Noi",
        "dest_name": "Thanh Hoa",
    }

    first = service.find_station_window(**kwargs)
    second = service.find_station_window(**kwargs)

    assert len(first) == 1
    assert first == second
    assert 30.0 <= first[0].distance_from_origin_km <= 230.0
    assert len(client.responses.requests) == 1
    request_input = client.responses.requests[0]["input"]
    assert "đoạn 30 km" in request_input
    assert "đoạn 230 km" in request_input


def test_fallback_provider_is_not_called_when_primary_has_candidates() -> None:
    station = CandidateStation(
        station_id="primary",
        name="Primary station",
        lat=20.5,
        lon=105.8,
        address="Primary",
        connector_types=["CCS2"],
        max_power_kw=60.0,
        detour_distance_km=0.0,
        detour_duration_min=0.0,
        freshness="FRESH",
        distance_from_origin_km=50.0,
    )
    primary = StaticStationService([station])
    fallback = StaticStationService(fail=True)
    service = FallbackStationDataService(primary=primary, fallback=fallback)

    assert _find(service) == [station]
    assert primary.calls == 1
    assert fallback.calls == 0


def test_fallback_provider_recovers_primary_failure() -> None:
    openai_service, _ = _search_service([SOURCE_URL])
    service = FallbackStationDataService(
        primary=StaticStationService(fail=True),
        fallback=openai_service,
    )

    stations = _find(service)

    assert len(stations) == 1
    assert stations[0].provenance is not None
    assert stations[0].provenance.retrieved_at <= datetime.now(UTC)


def test_fallback_provider_does_not_silently_return_empty_search() -> None:
    service = FallbackStationDataService(
        primary=StaticStationService(),
        fallback=StaticStationService(),
    )

    with pytest.raises(StationProviderError, match="without a grounded candidate"):
        _find(service)


def test_fallback_provider_surfaces_fallback_failure_after_empty_primary() -> None:
    service = FallbackStationDataService(
        primary=StaticStationService(),
        fallback=StaticStationService(fail=True),
    )

    with pytest.raises(StationProviderError, match="providers are unavailable"):
        _find(service)
