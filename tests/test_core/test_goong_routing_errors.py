import httpx
import pytest

from src.packages.core.trips.infrastructure.routing import (
    GoongRoutingProvider,
    RoutingUnavailableError,
)


def test_goong_not_found_preserves_provider_details(monkeypatch) -> None:
    calls = 0

    def fake_get(*args, **kwargs):
        nonlocal calls
        calls += 1
        request = httpx.Request("GET", "https://rsapi.goong.io/Direction")
        return httpx.Response(400, json={"status": "NOT_FOUND"}, request=request)

    monkeypatch.setattr(httpx, "get", fake_get)
    provider = GoongRoutingProvider(api_key="test-key", max_retries=3)

    with pytest.raises(RoutingUnavailableError) as captured:
        provider.get_route(23.0, 105.0, 8.61, 104.79)

    assert captured.value.http_status == 400
    assert captured.value.provider_status == "NOT_FOUND"
    assert captured.value.retryable is False
    assert calls == 1


def test_goong_rate_limit_opens_circuit_without_retry_storm(monkeypatch) -> None:
    calls = 0

    def fake_get(*args, **kwargs):
        nonlocal calls
        calls += 1
        request = httpx.Request("GET", "https://rsapi.goong.io/Direction")
        return httpx.Response(
            429,
            json={"status": "OVER_QUERY_LIMIT"},
            headers={"Retry-After": "2"},
            request=request,
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    provider = GoongRoutingProvider(
        api_key="test-key",
        max_retries=3,
        rate_limit_cooldown_seconds=5.0,
    )

    with pytest.raises(RoutingUnavailableError) as first:
        provider.get_route(21.0, 105.8, 20.9, 105.9)
    with pytest.raises(RoutingUnavailableError) as second:
        provider.get_route(21.0, 105.8, 20.8, 105.9)

    assert first.value.http_status == 429
    assert first.value.retry_after_seconds >= 5.0
    assert second.value.http_status == 429
    assert calls == 1
