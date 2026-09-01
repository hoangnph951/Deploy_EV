from __future__ import annotations

import hashlib
import logging
from dataclasses import replace
from datetime import UTC, datetime
from threading import Lock
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, Field

from src.packages.contracts.trips import DataProvenance
from src.packages.core.trips.application.errors import AppError
from src.packages.core.trips.domain.station_catalog import StationEvidence
from src.packages.core.trips.infrastructure.geocoding import GeocodeEntry
from src.packages.core.trips.infrastructure.routing import haversine_distance_km
from src.packages.core.trips.infrastructure.station_service import (
    CandidateStation,
    StationProviderError,
)

logger = logging.getLogger(__name__)


class Geocoder(Protocol):
    def resolve_text(self, query: str, field_name: str) -> GeocodeEntry: ...


class WebStationCandidate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    address: str = Field(min_length=4, max_length=500)
    connector_type: str = Field(min_length=2, max_length=50)
    max_power_kw: float = Field(gt=0, le=1000)
    port_count: int = Field(default=1, ge=1, le=100)
    source_url: str = Field(min_length=10, max_length=2000)
    evidence: str = Field(min_length=4, max_length=1000)


class WebStationSearchResult(BaseModel):
    candidates: list[WebStationCandidate] = Field(default_factory=list, max_length=20)


class OpenAIWebStationDataService:
    """Discover cited fallback candidates; exact routing and SOC stay downstream."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        geocoder: Geocoder,
        timeout_seconds: float = 20.0,
        base_url: str | None = None,
        allowed_domains: tuple[str, ...] = (),
        max_candidates: int = 12,
        client: OpenAI | None = None,
        evidence_repository=None,
    ):
        self._model = model.strip()
        self._geocoder = geocoder
        self._timeout_seconds = timeout_seconds
        self._allowed_domains = tuple(domain.strip() for domain in allowed_domains if domain.strip())
        self._max_candidates = max(1, min(max_candidates, 20))
        self._window_cache: dict[tuple, list[CandidateStation]] = {}
        self._window_cache_lock = Lock()
        self._client = client or OpenAI(
            api_key=api_key.strip(),
            base_url=base_url.strip() or None if base_url else None,
            timeout=timeout_seconds,
            max_retries=0,
        )
        self._evidence_repository = evidence_repository

    def find_corridor_stations(
        self,
        polyline: list[list[float]],
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        max_corridor_buffer_km: float = 15.0,
        max_detour_min: float = 15.0,
        required_connector: str = "CCS2",
        total_route_distance_km: float | None = None,
        origin_name: str = "Origin",
        dest_name: str = "Destination",
    ) -> list[CandidateStation]:
        if not polyline or not self._model:
            return []

        search_context = {
            "origin": {"name": origin_name, "lat": origin_lat, "lng": origin_lng},
            "destination": {"name": dest_name, "lat": dest_lat, "lng": dest_lng},
            "route_samples": _sample_polyline(polyline, 12),
            "corridor_radius_km": max_corridor_buffer_km,
            "required_connector": required_connector,
            "maximum_candidates": self._max_candidates,
        }
        tool: dict = {"type": "web_search"}
        if self._allowed_domains:
            tool["filters"] = {"allowed_domains": list(self._allowed_domains)}

        try:
            response = self._client.responses.parse(
                model=self._model,
                tools=[tool],
                tool_choice="auto",
                include=["web_search_call.action.sources"],
                max_tool_calls=4,
                max_output_tokens=3000,
                text_format=WebStationSearchResult,
                instructions=(
                    "Search the web for real public EV charging stations near the supplied Vietnam route. "
                    "Return a candidate only when a consulted source explicitly supports the station name, "
                    "address, required connector, and numeric charging power. Copy source_url from a source "
                    "you actually consulted. Do not infer missing connector or power values. Prefer official "
                    "operator pages and reputable map listings."
                ),
                input=str(search_context),
                timeout=self._timeout_seconds,
            )
        except (OpenAIError, ValueError, TypeError) as exc:
            # Keep authentication/configuration failures distinguishable from
            # an empty search result. This is essential for operators: a
            # 401 cannot be fixed by widening the route corridor.
            status_code = getattr(exc, "status_code", None)
            if status_code == 401:
                raise StationProviderError(
                    "OpenAI station web search authentication failed.",
                    code="OPENAI_AUTHENTICATION_FAILED",
                    http_status=401,
                    retryable=False,
                ) from exc
            raise StationProviderError("OpenAI station web search is unavailable.") from exc

        parsed = response.output_parsed
        if not isinstance(parsed, WebStationSearchResult):
            raise StationProviderError("OpenAI station web search returned no structured result.")

        source_urls = _collect_source_urls(response.model_dump())
        if not source_urls:
            return []

        retrieved_at = datetime.now(UTC)
        candidates: list[CandidateStation] = []
        seen_ids: set[str] = set()
        for item in parsed.candidates[: self._max_candidates]:
            source_url = _normalize_url(item.source_url)
            if source_url not in source_urls:
                continue
            if item.connector_type.strip().upper() != required_connector.strip().upper():
                continue
            try:
                location = self._geocoder.resolve_text(
                    f"{item.name}, {item.address}", "fallback_station"
                )
            except AppError:
                continue

            projected = _project_station(
                polyline,
                location.lat,
                location.lng,
                total_route_distance_km,
            )
            if projected is None:
                continue
            distance_to_route_km, distance_from_origin_km = projected
            if distance_to_route_km > max_corridor_buffer_km:
                continue
            detour_distance_km = distance_to_route_km * 2.0
            detour_duration_min = detour_distance_km / 40.0 * 60.0
            if detour_duration_min > max_detour_min:
                continue

            station_id = _station_id(item.name, item.address, source_url)
            if station_id in seen_ids:
                continue
            seen_ids.add(station_id)
            candidates.append(
                CandidateStation(
                    station_id=station_id,
                    name=item.name.strip(),
                    lat=location.lat,
                    lon=location.lng,
                    address=location.formatted_address,
                    connector_types=[required_connector.upper()],
                    max_power_kw=round(item.max_power_kw, 1),
                    detour_distance_km=round(detour_distance_km, 2),
                    detour_duration_min=round(detour_duration_min, 1),
                    freshness="STALE",
                    distance_from_origin_km=round(distance_from_origin_km, 2),
                    connector_standard=item.connector_type.strip(),
                    port_count=item.port_count,
                    station_status="UNVERIFIED",
                    access_type="Public (web evidence)",
                    provenance=DataProvenance(
                        kind="STATION_DETAIL",
                        source="OPENAI_WEB_SEARCH",
                        source_url=source_url,
                        retrieved_at=retrieved_at,
                        version=self._model,
                        served_at=retrieved_at,
                    ),
                    detail_quality="UNVERIFIED",
                )
            )
            if self._evidence_repository is not None:
                try:
                    self._evidence_repository.save_external_evidence(
                        StationEvidence(
                            provider="OPENAI_WEB_SEARCH",
                            field_name="station_candidate",
                            field_value=item.model_dump(mode="json"),
                            source_url=source_url,
                            retrieved_at=retrieved_at,
                            verification_status="UNVERIFIED",
                            raw_evidence={"evidence": item.evidence},
                        )
                    )
                except Exception:
                    logger.exception(
                        "station_external_evidence_persist_failed",
                        extra={"provider": "OPENAI_WEB_SEARCH", "source_url": source_url},
                    )

        candidates.sort(key=lambda station: station.distance_from_origin_km)
        return candidates

    def find_station_window(
        self,
        *,
        polyline: list[list[float]],
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        progress_start_km: float,
        progress_end_km: float,
        compatible_connectors: tuple[str, ...],
        max_corridor_buffer_km: float,
        max_detour_min: float,
        total_route_distance_km: float,
        max_detail_candidates: int = 48,
        target_candidate_count: int = 8,
        origin_radius_km: float | None = None,
        origin_name: str = "Origin",
        dest_name: str = "Destination",
        stale_station_hours_threshold: float | None = None,
    ) -> list[CandidateStation]:
        # Web-discovered stations are intentionally treated as stale/unverified;
        # the freshness threshold applies only to timestamped catalog data.
        del max_detail_candidates, origin_radius_km, stale_station_hours_threshold
        start_km = max(0.0, progress_start_km)
        end_km = min(total_route_distance_km, max(start_km, progress_end_km))
        if end_km <= start_km or not compatible_connectors:
            return []
        cache_key = (
            round(start_km, 1), round(end_km, 1),
            tuple(sorted(connector.upper() for connector in compatible_connectors)),
            round(max_corridor_buffer_km, 1), round(max_detour_min, 1),
        )
        with self._window_cache_lock:
            cached = self._window_cache.get(cache_key)
        if cached is not None:
            return cached[: max(1, target_candidate_count)]
        window_polyline = _slice_polyline_by_progress(
            polyline, start_km, end_km, total_route_distance_km
        )
        if len(window_polyline) < 2:
            return []
        window_origin = window_polyline[0]
        window_destination = window_polyline[-1]
        merged: dict[str, CandidateStation] = {}
        for connector in compatible_connectors:
            found = self.find_corridor_stations(
                polyline=window_polyline,
                origin_lat=window_origin[0], origin_lng=window_origin[1],
                dest_lat=window_destination[0], dest_lng=window_destination[1],
                max_corridor_buffer_km=max_corridor_buffer_km,
                max_detour_min=max_detour_min,
                required_connector=connector,
                total_route_distance_km=end_km - start_km,
                origin_name=f"{origin_name} (đoạn {start_km:.0f} km)",
                dest_name=f"{dest_name} (đoạn {end_km:.0f} km)",
            )
            for station in found:
                global_progress = start_km + station.distance_from_origin_km
                if start_km <= global_progress <= end_km:
                    merged.setdefault(
                        station.station_id,
                        replace(station, distance_from_origin_km=round(global_progress, 2)),
                    )
        result = sorted(
            merged.values(),
            key=lambda station: (
                station.distance_from_origin_km,
                station.detour_distance_km,
                -station.max_power_kw,
            ),
        )
        with self._window_cache_lock:
            self._window_cache[cache_key] = result
        return result[: max(1, target_candidate_count)]


def _sample_polyline(polyline: list[list[float]], limit: int) -> list[list[float]]:
    if len(polyline) <= limit:
        return polyline
    return [
        polyline[round(index * (len(polyline) - 1) / (limit - 1))]
        for index in range(limit)
    ]


def _slice_polyline_by_progress(
    polyline: list[list[float]],
    start_km: float,
    end_km: float,
    total_route_distance_km: float,
) -> list[list[float]]:
    if len(polyline) < 2 or total_route_distance_km <= 0:
        return polyline
    cumulative = [0.0]
    for start, end in zip(polyline, polyline[1:]):
        cumulative.append(
            cumulative[-1] + haversine_distance_km(start[0], start[1], end[0], end[1])
        )
    geometry_km = cumulative[-1]
    if geometry_km <= 0:
        return polyline
    scaled = [distance / geometry_km * total_route_distance_km for distance in cumulative]
    start_index = min(range(len(polyline)), key=lambda i: abs(scaled[i] - start_km))
    end_index = min(range(len(polyline)), key=lambda i: abs(scaled[i] - end_km))
    if end_index <= start_index:
        end_index = min(len(polyline) - 1, start_index + 1)
    return polyline[start_index : end_index + 1]


def _project_station(
    polyline: list[list[float]],
    lat: float,
    lon: float,
    total_route_distance_km: float | None,
) -> tuple[float, float] | None:
    if not polyline:
        return None
    cumulative = [0.0]
    for start, end in zip(polyline, polyline[1:]):
        cumulative.append(
            cumulative[-1] + haversine_distance_km(start[0], start[1], end[0], end[1])
        )
    nearest_index = min(
        range(len(polyline)),
        key=lambda index: haversine_distance_km(lat, lon, polyline[index][0], polyline[index][1]),
    )
    distance_to_route_km = haversine_distance_km(
        lat, lon, polyline[nearest_index][0], polyline[nearest_index][1]
    )
    geometry_distance_km = cumulative[-1]
    if geometry_distance_km <= 0.0:
        return None
    route_distance_km = total_route_distance_km or geometry_distance_km
    distance_from_origin_km = cumulative[nearest_index] / geometry_distance_km * route_distance_km
    if distance_from_origin_km <= 0.0 or distance_from_origin_km >= route_distance_km:
        return None
    return distance_to_route_km, distance_from_origin_km


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
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, ""))


def _station_id(name: str, address: str, source_url: str) -> str:
    identity = f"{name.strip().lower()}|{address.strip().lower()}|{source_url}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"openai-web-{digest}"
