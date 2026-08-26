from datetime import datetime

import pytest

from src.packages.core.trips.infrastructure.routing import (
    GoongRoutingProvider,
    RoutingUnavailableError,
    decode_polyline,
)


class StubResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "routes": [
                {
                    "legs": [
                        {
                            "distance": {"text": "293,4 km", "value": 293_400},
                            "duration": {"text": "4 giờ", "value": 14_400},
                        }
                    ],
                    "overview_polyline": {"points": "_p~iF~ps|U_ulLnnqC_mqNvxq`@"},
                }
            ]
        }


class StubWaypointResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "routes": [
                {
                    "legs": [
                        {"distance": {"value": 2_000}, "duration": {"value": 300}},
                        {"distance": {"value": 15_000}, "duration": {"value": 1_800}},
                    ],
                    "overview_polyline": {"points": "_p~iF~ps|U_ulLnnqC_mqNvxq`@"},
                }
            ]
        }


def test_decode_polyline_uses_lat_lng_order():
    assert decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@") == [
        [38.5, -120.2],
        [40.7, -120.95],
        [43.252, -126.453],
    ]


def test_goong_routes_parses_distance_duration_and_polyline(monkeypatch):
    captured = {}

    def fake_get(url, *, params, timeout, follow_redirects):
        captured.update(url=url, params=params, timeout=timeout, follow_redirects=follow_redirects)
        return StubResponse()

    monkeypatch.setattr("src.packages.core.trips.infrastructure.routing.httpx.get", fake_get)
    provider = GoongRoutingProvider(api_key="server-key", max_retries=0)

    result = provider.get_route(21.0278, 105.8342, 18.6796, 105.6813)

    assert result.provider == "GOONG_DIRECTIONS"
    assert result.distance_km == 293.4
    assert result.duration_min == 240.0
    assert len(result.polyline) == 3
    assert isinstance(result.retrieved_at, datetime)
    assert captured["url"] == "https://rsapi.goong.io/Direction"
    assert captured["params"]["origin"] == "21.0278,105.8342"
    assert captured["params"]["destination"] == "18.6796,105.6813"
    assert "server-key" not in result.source_url


def test_goong_routes_fails_closed_when_api_key_is_missing():
    provider = GoongRoutingProvider(api_key="")

    with pytest.raises(RoutingUnavailableError, match="GOONG_API_KEY"):
        provider.get_route(21.0278, 105.8342, 18.6796, 105.6813)


def test_goong_routes_preserves_waypoint_legs(monkeypatch):
    monkeypatch.setattr(
        "src.packages.core.trips.infrastructure.routing.httpx.get",
        lambda *args, **kwargs: StubWaypointResponse(),
    )
    monkeypatch.setattr(
        "src.packages.core.trips.infrastructure.routing.decode_polyline",
        lambda _: [[21.0053, 105.8470], [21.01, 105.84], [20.9948, 105.9464]],
    )
    provider = GoongRoutingProvider(api_key="server-key", max_retries=0)

    result = provider.get_route(
        21.0053,
        105.8470,
        20.9948,
        105.9464,
        waypoints=[(21.01, 105.84)],
    )

    assert result.distance_km == 17.0
    assert [segment.distance_km for segment in result.segments] == [2.0, 15.0]
    assert result.segments[0].end_lat == 21.01
    assert result.segments[-1].to_name == "Destination"


def test_goong_routes_rejects_geometry_that_skips_required_waypoint(monkeypatch):
    monkeypatch.setattr(
        "src.packages.core.trips.infrastructure.routing.httpx.get",
        lambda *args, **kwargs: StubWaypointResponse(),
    )
    monkeypatch.setattr(
        "src.packages.core.trips.infrastructure.routing.decode_polyline",
        lambda _: [[21.0053, 105.8470], [20.9948, 105.9464]],
    )
    provider = GoongRoutingProvider(api_key="server-key", max_retries=0)

    with pytest.raises(RoutingUnavailableError, match="required charging stop"):
        provider.get_route(
            21.0053,
            105.8470,
            20.9948,
            105.9464,
            waypoints=[(19.734034, 105.899574)],
        )
