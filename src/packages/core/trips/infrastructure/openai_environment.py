from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, Field

from src.packages.contracts.trips import DataProvenance, EnvironmentSnapshot
from src.packages.core.trips.infrastructure.environment import EnvironmentProviderError


class WebEnvironmentSearchResult(BaseModel):
    temperature_c: float = Field(ge=-80.0, le=60.0)
    precipitation_mm: float = Field(ge=0.0, le=1000.0)
    wind_speed_kmh: float = Field(ge=0.0, le=300.0)
    elevation_gain_m: float = Field(ge=0.0, le=30000.0)
    elevation_loss_m: float = Field(ge=0.0, le=30000.0)
    weather_source_url: str = Field(min_length=10, max_length=2000)
    elevation_source_url: str = Field(min_length=10, max_length=2000)
    weather_evidence: str = Field(min_length=4, max_length=1000)
    elevation_evidence: str = Field(min_length=4, max_length=1000)


class OpenAIWebEnvironmentProvider:
    """Retrieve cited, explicitly degraded environment estimates via web search."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 20.0,
        consumption_margin_percent: float = 15.0,
        client: OpenAI | None = None,
    ):
        self._model = model.strip()
        self._timeout_seconds = timeout_seconds
        self._consumption_margin_percent = max(0.0, consumption_margin_percent)
        self._client = client or OpenAI(
            api_key=api_key.strip(),
            timeout=timeout_seconds,
            max_retries=0,
        )

    def get_snapshot(
        self,
        polyline: list[list[float]],
        *,
        fallback_temperature_c: float | None = None,
    ) -> EnvironmentSnapshot:
        if not polyline or not self._model:
            raise EnvironmentProviderError(
                "Route geometry and an OpenAI model are required for environment web search."
            )

        context = {
            "route_samples": _sample_polyline(polyline, 7),
            "fallback_temperature_c": fallback_temperature_c,
            "requested_at_utc": datetime.now(UTC).isoformat(),
        }
        try:
            response = self._client.responses.parse(
                model=self._model,
                tools=[{"type": "web_search"}],
                tool_choice="auto",
                include=["web_search_call.action.sources"],
                max_tool_calls=6,
                max_output_tokens=2200,
                text_format=WebEnvironmentSearchResult,
                instructions=(
                    "Search the web for recent weather and documented terrain/elevation information "
                    "for the supplied Vietnam route samples. Return temperature, precipitation, and "
                    "wind representative of the route now. Return conservative estimates of cumulative "
                    "elevation gain and loss for the corridor. Every value must be supported by a source "
                    "you actually consulted; copy the exact consulted URLs into the source URL fields. "
                    "Prefer official meteorological, geographic, or map sources. Do not claim that the "
                    "elevation profile is exact. If the sources cannot support all required values, do "
                    "not invent them and do not return a structured result."
                ),
                input=json.dumps(context, ensure_ascii=False),
                timeout=self._timeout_seconds,
            )
        except (OpenAIError, TypeError, ValueError) as exc:
            raise EnvironmentProviderError(
                "OpenAI environment web search is unavailable."
            ) from exc

        parsed = response.output_parsed
        if not isinstance(parsed, WebEnvironmentSearchResult):
            raise EnvironmentProviderError(
                "OpenAI environment web search returned no structured result."
            )

        consulted_urls = _collect_source_urls(response.model_dump())
        weather_url = _normalize_url(parsed.weather_source_url)
        elevation_url = _normalize_url(parsed.elevation_source_url)
        if weather_url not in consulted_urls or elevation_url not in consulted_urls:
            raise EnvironmentProviderError(
                "OpenAI environment web search returned unverified source URLs."
            )

        retrieved_at = datetime.now(UTC)
        return EnvironmentSnapshot(
            temperature_c=parsed.temperature_c,
            precipitation_mm=parsed.precipitation_mm,
            wind_speed_kmh=parsed.wind_speed_kmh,
            elevation_gain_m=parsed.elevation_gain_m,
            elevation_loss_m=parsed.elevation_loss_m,
            weather_provenance=DataProvenance(
                source="OPENAI_WEB_SEARCH",
                source_url=weather_url,
                retrieved_at=retrieved_at,
                version=self._model,
            ),
            elevation_provenance=DataProvenance(
                source="OPENAI_WEB_SEARCH",
                source_url=elevation_url,
                retrieved_at=retrieved_at,
                version=self._model,
            ),
            status="WEB_SEARCH",
            is_degraded=True,
            consumption_margin_percent=self._consumption_margin_percent,
            warning=(
                "Open-Meteo không khả dụng; kế hoạch dùng dữ liệu web có dẫn nguồn "
                "qua OpenAI và biên tiêu hao dự phòng."
            ),
        )


def _sample_polyline(polyline: list[list[float]], limit: int) -> list[list[float]]:
    if len(polyline) <= limit:
        return polyline
    last_index = len(polyline) - 1
    indices = sorted({round(index * last_index / (limit - 1)) for index in range(limit)})
    return [polyline[index] for index in indices]


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
