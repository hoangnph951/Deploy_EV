from __future__ import annotations

import httpx
import pytest

from src.packages.core.trips.infrastructure.environment import (
    EnvironmentProviderError,
    OpenMeteoEnvironmentProvider,
    StaticEnvironmentProvider,
)


class _FakeClient:
    def __init__(self, responses: list[httpx.Response]):
        self.responses = responses
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def get(self, url: str, *, params: dict[str, object]):
        del params
        response = self.responses[self.calls]
        self.calls += 1
        if response.request is None:
            response.request = httpx.Request("GET", url)
        return response


def _response(status_code: int, payload: dict, *, retry_after: str | None = None):
    headers = {"Retry-After": retry_after} if retry_after is not None else None
    return httpx.Response(
        status_code,
        json=payload,
        headers=headers,
        request=httpx.Request("GET", "https://api.open-meteo.test/v1"),
    )


def test_open_meteo_retries_429_then_returns_snapshot(monkeypatch):
    fake_client = _FakeClient(
        [
            _response(429, {"error": True}, retry_after="0"),
            _response(
                200,
                {
                    "current": {
                        "time": "2026-08-27T00:00",
                        "temperature_2m": 27.0,
                        "precipitation": 0.0,
                        "wind_speed_10m": 4.0,
                    }
                },
            ),
            _response(200, {"elevation": [10.0, 30.0]}),
        ]
    )
    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: fake_client)

    provider = OpenMeteoEnvironmentProvider(
        max_retries=1,
        retry_base_delay_seconds=0,
    )
    snapshot = provider.get_snapshot([[21.0, 105.0], [20.0, 106.0]])

    assert fake_client.calls == 3
    assert snapshot.temperature_c == 27.0
    assert snapshot.elevation_gain_m == 20.0
    assert snapshot.elevation_loss_m == 0.0
    assert snapshot.status == "LIVE"
    assert snapshot.is_degraded is False


def test_open_meteo_logs_provider_and_status_before_failing(monkeypatch, caplog):
    fake_client = _FakeClient([_response(403, {"error": True})])
    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: fake_client)
    provider = OpenMeteoEnvironmentProvider(
        max_retries=2,
        retry_base_delay_seconds=0,
        fallback_enabled=False,
    )

    with pytest.raises(EnvironmentProviderError, match="weather.*HTTP 403"):
        provider.get_snapshot([[21.0, 105.0], [20.0, 106.0]])

    assert "Open-Meteo weather request failed status=403 attempt=1/3" in caplog.text
    assert fake_client.calls == 1


def test_open_meteo_uses_policy_fallback_with_consumption_margin(monkeypatch):
    fake_client = _FakeClient([_response(503, {"error": True})])
    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: fake_client)
    provider = OpenMeteoEnvironmentProvider(
        max_retries=0,
        retry_base_delay_seconds=0,
        fallback_consumption_margin_percent=20.0,
    )

    snapshot = provider.get_snapshot(
        [[21.0, 105.0], [20.0, 106.0]],
        fallback_temperature_c=28.0,
    )

    assert snapshot.status == "POLICY_FALLBACK"
    assert snapshot.is_degraded is True
    assert snapshot.temperature_c == 28.0
    assert snapshot.consumption_margin_percent == 20.0
    assert snapshot.weather_provenance.source == "POLICY_FALLBACK"
    assert "biên tiêu hao dự phòng" in (snapshot.warning or "")


def test_open_meteo_uses_recent_route_cache_before_policy_fallback(monkeypatch):
    fake_client = _FakeClient(
        [
            _response(
                200,
                {
                    "current": {
                        "time": "2026-08-27T00:00",
                        "temperature_2m": 27.0,
                        "precipitation": 0.0,
                        "wind_speed_10m": 4.0,
                    }
                },
            ),
            _response(200, {"elevation": [10.0, 30.0]}),
            _response(503, {"error": True}),
        ]
    )
    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: fake_client)
    provider = OpenMeteoEnvironmentProvider(
        max_retries=0,
        retry_base_delay_seconds=0,
        cache_ttl_seconds=3600,
        cached_consumption_margin_percent=5.0,
    )
    polyline = [[21.0, 105.0], [20.0, 106.0]]

    live = provider.get_snapshot(polyline)
    cached = provider.get_snapshot(polyline)

    assert live.status == "LIVE"
    assert cached.status == "CACHED"
    assert cached.is_degraded is True
    assert cached.temperature_c == live.temperature_c
    assert cached.elevation_gain_m == live.elevation_gain_m
    assert cached.consumption_margin_percent == 5.0
    assert fake_client.calls == 3


def test_open_meteo_uses_search_fallback_when_live_and_cache_are_unavailable(monkeypatch):
    fake_client = _FakeClient([_response(503, {"error": True})])
    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: fake_client)

    class _SearchFallback(StaticEnvironmentProvider):
        calls = 0

        def get_snapshot(self, polyline, *, fallback_temperature_c=None):
            self.calls += 1
            snapshot = super().get_snapshot(
                polyline, fallback_temperature_c=fallback_temperature_c
            )
            return snapshot.model_copy(
                update={
                    "status": "WEB_SEARCH",
                    "is_degraded": True,
                    "consumption_margin_percent": 15.0,
                }
            )

    search_fallback = _SearchFallback()
    provider = OpenMeteoEnvironmentProvider(
        max_retries=0,
        cache_ttl_seconds=0,
        search_fallback_provider=search_fallback,
    )

    snapshot = provider.get_snapshot([[21.0, 105.0], [20.0, 106.0]])

    assert search_fallback.calls == 1
    assert snapshot.status == "WEB_SEARCH"
    assert snapshot.consumption_margin_percent == 15.0
