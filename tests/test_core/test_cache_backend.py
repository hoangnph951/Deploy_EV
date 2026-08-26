from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from src.packages.core.trips.infrastructure.cache_backend import (
    CacheBackendError,
    InMemoryCacheBackend,
    RedisCacheBackend,
)
from src.packages.core.trips.infrastructure.routing import (
    GoongRoutingProvider,
    route_cache_key,
)


def _goong_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "routes": [
                {
                    "legs": [
                        {"distance": {"value": 12340}, "duration": {"value": 900}}
                    ],
                    "overview_polyline": {"points": "_p~iF~ps|U_ulLnnqC"},
                }
            ]
        },
    )


def test_in_memory_cache_ttl_and_lock(monkeypatch) -> None:
    now = [100.0]
    monkeypatch.setattr(
        "src.packages.core.trips.infrastructure.cache_backend.time.monotonic",
        lambda: now[0],
    )
    cache = InMemoryCacheBackend()
    cache.set("key", b"value", ttl_seconds=5)
    assert cache.get("key") == b"value"
    with cache.lock("lock"):
        pass
    now[0] = 106.0
    assert cache.get("key") is None


class _FakeRedis:
    def __init__(self):
        self.values: dict[str, bytes] = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, **_kwargs):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


def test_redis_backend_round_trip_without_business_importing_redis() -> None:
    fake = _FakeRedis()
    cache = RedisCacheBackend("redis://unused", client=fake)
    cache.set("key", b"value", ttl_seconds=5)
    assert cache.get("key") == b"value"
    cache.delete("key")
    assert cache.get("key") is None


def test_goong_cache_uses_canonical_key_and_preserves_source_timestamp(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        "src.packages.core.trips.infrastructure.routing.httpx.get",
        lambda *args, **kwargs: calls.append((args, kwargs)) or _goong_response(),
    )
    cache = InMemoryCacheBackend()
    provider = GoongRoutingProvider(
        api_key="redacted",
        max_retries=0,
        min_request_interval_seconds=0,
        cache_backend=cache,
    )
    first = provider.get_route(10.1234564, 106.0, 11.0, 107.0)
    second = provider.get_route(10.1234564, 106.0, 11.0, 107.0)
    assert len(calls) == 1
    assert second == first
    assert isinstance(second.retrieved_at, datetime)
    assert second.retrieved_at.tzinfo == UTC
    key = route_cache_key(
        provider="GOONG_DIRECTIONS",
        origin_lat=10.1234564,
        origin_lng=106.0,
        dest_lat=11.0,
        dest_lng=107.0,
    )
    assert key.startswith("route:v1:GOONG_DIRECTIONS:10.123456,106.000000:")
    assert cache.get(key) is not None


class _BrokenCache:
    def get(self, _key):
        raise CacheBackendError("down")

    def set(self, _key, _value, *, ttl_seconds):
        raise CacheBackendError("down")

    def delete(self, _key):
        raise CacheBackendError("down")

    def lock(self, _key, *, timeout_seconds=10):
        raise CacheBackendError("down")


def test_cache_outage_falls_back_to_route_provider(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.packages.core.trips.infrastructure.routing.httpx.get",
        lambda *_args, **_kwargs: _goong_response(),
    )
    result = GoongRoutingProvider(
        api_key="redacted",
        max_retries=0,
        min_request_interval_seconds=0,
        cache_backend=_BrokenCache(),
    ).get_route(10.0, 106.0, 11.0, 107.0)
    assert result.provider == "GOONG_DIRECTIONS"
    assert result.distance_km == pytest.approx(12.34)
