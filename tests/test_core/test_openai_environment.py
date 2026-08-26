from __future__ import annotations

import pytest

from src.packages.core.trips.infrastructure.environment import EnvironmentProviderError
from src.packages.core.trips.infrastructure.openai_environment import (
    OpenAIWebEnvironmentProvider,
    WebEnvironmentSearchResult,
)

WEATHER_URL = "https://weather.example.test/current"
ELEVATION_URL = "https://terrain.example.test/route"


class _FakeResponse:
    def __init__(self, source_urls: list[str]):
        self.output_parsed = WebEnvironmentSearchResult(
            temperature_c=28.0,
            precipitation_mm=1.5,
            wind_speed_kmh=12.0,
            elevation_gain_m=320.0,
            elevation_loss_m=280.0,
            weather_source_url=WEATHER_URL,
            elevation_source_url=ELEVATION_URL,
            weather_evidence="Recent weather observations for the route corridor.",
            elevation_evidence="Published terrain information for the route corridor.",
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
                }
            ]
        }


class _FakeResponses:
    def __init__(self, response: _FakeResponse):
        self.response = response
        self.requests: list[dict] = []

    def parse(self, **kwargs):
        self.requests.append(kwargs)
        return self.response


class _FakeOpenAI:
    def __init__(self, response: _FakeResponse):
        self.responses = _FakeResponses(response)


def _provider(source_urls: list[str]):
    client = _FakeOpenAI(_FakeResponse(source_urls))
    provider = OpenAIWebEnvironmentProvider(
        api_key="test-key",
        model="test-web-model",
        consumption_margin_percent=15.0,
        client=client,
    )
    return provider, client


def test_openai_environment_returns_cited_degraded_snapshot() -> None:
    provider, client = _provider([WEATHER_URL, ELEVATION_URL])

    snapshot = provider.get_snapshot([[21.0, 105.8], [20.0, 106.0]])

    assert snapshot.status == "WEB_SEARCH"
    assert snapshot.is_degraded is True
    assert snapshot.temperature_c == 28.0
    assert snapshot.elevation_gain_m == 320.0
    assert snapshot.consumption_margin_percent == 15.0
    assert snapshot.weather_provenance.source == "OPENAI_WEB_SEARCH"
    assert snapshot.weather_provenance.source_url == WEATHER_URL
    assert snapshot.elevation_provenance.source_url == ELEVATION_URL
    request = client.responses.requests[0]
    assert request["tools"] == [{"type": "web_search"}]
    assert request["include"] == ["web_search_call.action.sources"]
    assert request["text_format"] is WebEnvironmentSearchResult


def test_openai_environment_rejects_unconsulted_source_url() -> None:
    provider, _ = _provider([WEATHER_URL])

    with pytest.raises(EnvironmentProviderError, match="unverified source URLs"):
        provider.get_snapshot([[21.0, 105.8], [20.0, 106.0]])
