from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, Field


@dataclass(frozen=True)
class EndpointRecoverySuggestion:
    name: str
    address: str
    source_url: str
    evidence: str


class RecoveryAdvisor(Protocol):
    def suggest_endpoint_access(
        self,
        *,
        origin_name: str,
        origin_lat: float,
        origin_lng: float,
        destination_name: str,
        destination_lat: float,
        destination_lng: float,
        provider_status: str | None,
    ) -> list[EndpointRecoverySuggestion]: ...


class NullRecoveryAdvisor:
    def suggest_endpoint_access(self, **kwargs) -> list[EndpointRecoverySuggestion]:
        return []


class _EndpointCandidate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    address: str = Field(min_length=4, max_length=500)
    source_url: str = Field(min_length=10, max_length=2000)
    evidence: str = Field(min_length=4, max_length=1000)


class _EndpointSearchResult(BaseModel):
    candidates: list[_EndpointCandidate] = Field(default_factory=list, max_length=8)


class OpenAIRecoveryAdvisor:
    """Suggest cited access points; routing and energy remain authoritative."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 20.0,
        base_url: str | None = None,
        client: OpenAI | None = None,
    ):
        self._model = model.strip()
        self._timeout_seconds = timeout_seconds
        # Recovery is optional. Avoid automatic retries multiplying quota pressure;
        # the deterministic planner can continue without an AI suggestion.
        self._client = client or OpenAI(
            api_key=api_key.strip(),
            base_url=base_url.strip() or None if base_url else None,
            timeout=timeout_seconds,
            max_retries=0,
        )

    def suggest_endpoint_access(
        self,
        *,
        origin_name: str,
        origin_lat: float,
        origin_lng: float,
        destination_name: str,
        destination_lat: float,
        destination_lng: float,
        provider_status: str | None,
    ) -> list[EndpointRecoverySuggestion]:
        if not self._model:
            return []
        facts = {
            "origin": {"name": origin_name, "lat": origin_lat, "lng": origin_lng},
            "requested_destination": {
                "name": destination_name,
                "lat": destination_lat,
                "lng": destination_lng,
            },
            "routing_provider": "Goong Directions",
            "provider_status": provider_status,
        }
        try:
            response = self._client.responses.parse(
                model=self._model,
                tools=[{"type": "web_search"}],
                tool_choice="auto",
                include=["web_search_call.action.sources"],
                max_tool_calls=4,
                max_output_tokens=2200,
                text_format=_EndpointSearchResult,
                instructions=(
                    "Find real, publicly documented road-accessible entrances or visitor access points "
                    "near the supplied Vietnam destination. Return only places supported by a consulted "
                    "source. Do not calculate a route, driving distance, battery SOC, or charging plan. "
                    "Do not claim that a point is routable; downstream Goong validation decides that."
                ),
                input=str(facts),
                timeout=self._timeout_seconds,
            )
        except (OpenAIError, TypeError, ValueError):
            return []

        parsed = response.output_parsed
        if not isinstance(parsed, _EndpointSearchResult):
            return []
        consulted_urls = _collect_source_urls(response.model_dump())
        suggestions: list[EndpointRecoverySuggestion] = []
        for item in parsed.candidates:
            source_url = _normalize_url(item.source_url)
            if source_url not in consulted_urls:
                continue
            suggestions.append(
                EndpointRecoverySuggestion(
                    name=item.name.strip(),
                    address=item.address.strip(),
                    source_url=source_url,
                    evidence=item.evidence.strip(),
                )
            )
        return suggestions


def _collect_source_urls(payload: object) -> set[str]:
    urls: set[str] = set()
    if isinstance(payload, dict):
        if payload.get("type") == "web_search_call":
            action = payload.get("action")
            sources = action.get("sources") if isinstance(action, dict) else None
            if isinstance(sources, list):
                for source in sources:
                    url = source.get("url") if isinstance(source, dict) else None
                    if isinstance(url, str):
                        normalized = _normalize_url(url)
                        if normalized:
                            urls.add(normalized)
        for value in payload.values():
            urls.update(_collect_source_urls(value))
    elif isinstance(payload, list):
        for item in payload:
            urls.update(_collect_source_urls(item))
    return urls


def _normalize_url(value: str) -> str:
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return ""
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, "")
    )
