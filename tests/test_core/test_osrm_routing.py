from datetime import UTC, datetime

import httpx
import pytest

from src.packages.core.trips.infrastructure.osrm_routing import OsrmRoutingProvider


class _Client:
    def __init__(self, responses: list[httpx.Response]):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url, *, params):
        self.calls.append((str(url), dict(params)))
        return self.responses.pop(0)


def _response(payload: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("GET", "http://osrm.test/request"),
    )


def test_osrm_table_is_one_to_many_and_uses_longitude_latitude_order() -> None:
    client = _Client(
        [
            _response(
                {
                    "code": "Ok",
                    "distances": [[12_000.0, None]],
                    "durations": [[900.0, None]],
                }
            )
        ]
    )
    provider = OsrmRoutingProvider(base_url="http://osrm.test", client=client)

    cells = provider.get_route_matrix(21.0, 105.0, [(10.0, 106.0), (11.0, 107.0)])

    assert cells[0].distance_km == 12.0
    assert cells[0].duration_minutes == 15.0
    assert cells[0].provider == "OSRM"
    assert cells[1] is None
    url, params = client.calls[0]
    assert "105.000000,21.000000;106.000000,10.000000" in url
    assert params["sources"] == "0"
    assert params["destinations"] == "1;2"
    assert params["annotations"] == "distance,duration"
    assert "fallback_speed" not in params


def test_osrm_table_treats_nonpositive_distance_as_unusable_edge() -> None:
    client = _Client(
        [
            _response(
                {
                    "code": "Ok",
                    "distances": [[0.0, -1.2, 1_250.0]],
                    "durations": [[0.0, 0.0, 180.0]],
                }
            )
        ]
    )
    provider = OsrmRoutingProvider(base_url="http://osrm.test", client=client)

    cells = provider.get_route_matrix(
        21.0,
        105.0,
        [(21.0, 105.0), (21.0, 105.0), (21.01, 105.01)],
    )

    assert cells[0] is None
    assert cells[1] is None
    assert cells[2] is not None
    assert cells[2].distance_km == 1.25


def test_osrm_route_maps_geojson_to_domain_latitude_longitude() -> None:
    client = _Client(
        [
            _response(
                {
                    "code": "Ok",
                    "routes": [
                        {
                            "distance": 12_500.0,
                            "duration": 1_000.0,
                            "geometry": {
                                "type": "LineString",
                                "coordinates": [[105.0, 21.0], [106.0, 10.0]],
                            },
                            "legs": [{"distance": 12_500.0, "duration": 1_000.0}],
                        }
                    ],
                }
            )
        ]
    )
    provider = OsrmRoutingProvider(base_url="http://osrm.test", client=client)

    route = provider.get_route(21.0, 105.0, 10.0, 106.0)

    assert route.provider == "OSRM"
    assert route.polyline == [[21.0, 105.0], [10.0, 106.0]]
    assert route.distance_km == 12.5
    assert route.duration_min == pytest.approx(16.667)
    assert route.retrieved_at <= datetime.now(UTC)


def test_osrm_table_fails_before_http_when_location_limit_is_exceeded() -> None:
    client = _Client([])
    provider = OsrmRoutingProvider(
        base_url="http://osrm.test",
        max_table_locations=2,
        client=client,
    )

    with pytest.raises(ValueError, match="location limit"):
        provider.get_route_matrix(21.0, 105.0, [(10.0, 106.0), (11.0, 107.0)])

    assert client.calls == []
