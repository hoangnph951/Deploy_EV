from __future__ import annotations

import json
import logging
import math
import time
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Literal, Protocol

import httpx

# pyrefly: ignore [missing-import]
from src.packages.contracts.trips import DataProvenance
from src.packages.core.trips.infrastructure.cache_backend import (
    CacheBackend,
    CacheBackendError,
)
from src.packages.core.trips.infrastructure.fixtures.station_fixtures import (
    StationSnapshotFixture,
    load_station_fixtures,
)
from src.packages.core.trips.infrastructure.routing import haversine_distance_km

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CandidateStation:
    station_id: str
    name: str
    lat: float
    lon: float
    address: str
    connector_types: list[str]
    max_power_kw: float
    detour_distance_km: float
    detour_duration_min: float
    freshness: Literal["FRESH", "STALE", "EXPIRED"]
    distance_from_origin_km: float
    connector_standard: str = "IEC_62196_T2_COMBO"
    port_count: int = 1
    station_status: str = "ACTIVE"
    opening_24_7: bool | None = None
    access_type: str = "Public"
    parking_fee: bool | None = None
    station_updated_at: datetime | None = None
    provenance: DataProvenance | None = None
    catalog_location_id: int | None = None
    detail_quality: Literal["VERIFIED", "PARTIAL", "UNVERIFIED"] = "PARTIAL"


class StationProviderError(RuntimeError):
    """Typed station-provider failure that preserves recovery semantics."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "STATION_PROVIDER_UNAVAILABLE",
        http_status: int | None = None,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class ProviderCircuitState:
    reason: str
    opened_at: datetime
    retry_after_seconds: float


class ProviderCircuitBreaker:
    """Prevent repeated calls while an upstream denial/rate limit is active."""

    def __init__(
        self,
        *,
        default_cooldown_seconds: float = 300.0,
        cache_backend: CacheBackend | None = None,
        cache_key: str | None = None,
    ):
        self._default_cooldown_seconds = max(1.0, default_cooldown_seconds)
        self._lock = Lock()
        self._state: ProviderCircuitState | None = None
        self._open_until_monotonic = 0.0
        self._cache_backend = cache_backend
        self._cache_key = cache_key

    def open(self, *, reason: str, retry_after_seconds: float | None = None) -> None:
        cooldown = (
            self._default_cooldown_seconds
            if retry_after_seconds is None
            else max(1.0, float(retry_after_seconds))
        )
        opened_at = datetime.now(UTC)
        with self._lock:
            self._state = ProviderCircuitState(
                reason=reason,
                opened_at=opened_at,
                retry_after_seconds=cooldown,
            )
            self._open_until_monotonic = time.monotonic() + cooldown
        if self._cache_backend is not None and self._cache_key:
            try:
                self._cache_backend.set(
                    self._cache_key,
                    json.dumps(
                        {
                            "state": "OPEN",
                            "reason": reason,
                            "opened_at": opened_at.isoformat(),
                            "retry_at": opened_at.timestamp() + cooldown,
                        },
                        separators=(",", ":"),
                    ).encode("utf-8"),
                    ttl_seconds=cooldown,
                )
            except CacheBackendError:
                pass

    def current_state(self) -> ProviderCircuitState | None:
        if self._cache_backend is not None and self._cache_key:
            try:
                shared = self._cache_backend.get(self._cache_key)
                if shared is not None:
                    payload = json.loads(shared.decode("utf-8"))
                    opened_at = datetime.fromisoformat(payload["opened_at"])
                    remaining = max(
                        0.0,
                        float(payload["retry_at"]) - datetime.now(UTC).timestamp(),
                    )
                    if remaining > 0:
                        return ProviderCircuitState(
                            reason=str(payload["reason"]),
                            opened_at=opened_at,
                            retry_after_seconds=remaining,
                        )
            except (
                CacheBackendError,
                ValueError,
                TypeError,
                KeyError,
                json.JSONDecodeError,
            ):
                pass
        with self._lock:
            if self._state is None:
                return None
            if time.monotonic() >= self._open_until_monotonic:
                self._state = None
                self._open_until_monotonic = 0.0
                return None
            remaining = max(0.0, self._open_until_monotonic - time.monotonic())
            return ProviderCircuitState(
                reason=self._state.reason,
                opened_at=self._state.opened_at,
                retry_after_seconds=remaining,
            )

    def close(self) -> None:
        with self._lock:
            self._state = None
            self._open_until_monotonic = 0.0
        if self._cache_backend is not None and self._cache_key:
            try:
                self._cache_backend.delete(self._cache_key)
            except CacheBackendError:
                pass


class VinFastAccessDeniedError(StationProviderError):
    """Raised when VinFast upstream endpoint returns HTTP 403 or anti-bot WAF challenge."""

    def __init__(
        self,
        message: str = "VinFast request was blocked by the upstream anti-bot/WAF layer.",
        *,
        http_status: int = 403,
        provider_status: str = "ACCESS_DENIED",
    ):
        super().__init__(
            message,
            code="PROVIDER_ACCESS_DENIED",
            http_status=http_status,
            retryable=False,
        )
        self.provider_status = provider_status


class StationService(Protocol):
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
    ) -> list[CandidateStation]: ...

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
    ) -> list[CandidateStation]: ...


class FallbackStationDataService:
    """Use a secondary discovery provider when primary data is absent or unavailable."""

    def __init__(self, *, primary: StationService, fallback: StationService):
        self._primary = primary
        self._fallback = fallback

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
        kwargs = {
            "polyline": polyline,
            "origin_lat": origin_lat,
            "origin_lng": origin_lng,
            "dest_lat": dest_lat,
            "dest_lng": dest_lng,
            "max_corridor_buffer_km": max_corridor_buffer_km,
            "max_detour_min": max_detour_min,
            "required_connector": required_connector,
            "total_route_distance_km": total_route_distance_km,
            "origin_name": origin_name,
            "dest_name": dest_name,
        }
        primary_error: StationProviderError | None = None
        try:
            primary_candidates = self._primary.find_corridor_stations(**kwargs)
        except StationProviderError as exc:
            primary_error = exc
        else:
            if primary_candidates:
                return primary_candidates

        try:
            fallback_candidates = self._fallback.find_corridor_stations(**kwargs)
        except StationProviderError as exc:
            if isinstance(primary_error, VinFastAccessDeniedError):
                raise primary_error from exc
            raise StationProviderError(
                "Primary and fallback station data providers are unavailable.",
                code=exc.code,
                http_status=exc.http_status,
                retryable=exc.retryable,
                retry_after_seconds=exc.retry_after_seconds,
            ) from exc
        if fallback_candidates:
            return fallback_candidates
        raise StationProviderError(
            "Station web search completed without a grounded candidate for this route."
        )

    def find_station_window(self, **kwargs) -> list[CandidateStation]:
        target = max(1, int(kwargs.get("target_candidate_count", 8)))
        primary_error: StationProviderError | None = None
        try:
            primary = _find_station_window(self._primary, **kwargs)
        except StationProviderError as exc:
            primary_error = exc
            primary = []
        if len(primary) >= target:
            return primary

        try:
            fallback = _find_station_window(self._fallback, **kwargs)
        except StationProviderError as exc:
            if primary_error is not None and not primary:
                if isinstance(primary_error, VinFastAccessDeniedError):
                    raise primary_error from exc
                raise StationProviderError(
                    "Primary and fallback station data providers are unavailable.",
                    code=exc.code,
                    http_status=exc.http_status,
                    retryable=exc.retryable,
                    retry_after_seconds=exc.retry_after_seconds,
                ) from exc
            if not primary:
                raise StationProviderError(
                    "Fallback station search is unavailable and the primary search returned no candidates."
                ) from exc
            fallback = []

        merged = {station.station_id: station for station in primary}
        for station in fallback:
            merged.setdefault(station.station_id, station)
        ordered = sorted(
            merged.values(),
            key=lambda station: (
                station.distance_from_origin_km,
                station.detour_distance_km,
                -station.max_power_kw,
            ),
        )
        if ordered:
            return ordered
        raise StationProviderError(
            "Station search completed without a grounded candidate in the requested window."
        )

    def find_official_station_window(self, **kwargs) -> list[CandidateStation]:
        """Search only the authoritative provider during deterministic planning."""
        try:
            return _find_station_window(self._primary, **kwargs)
        except StationProviderError:
            # A stale/empty local catalog must not mask the live official
            # VinFast locator. This fallback remains authoritative (unlike the
            # OpenAI web-search recovery provider).
            if isinstance(self._fallback, VinFastStationDataService):
                return _find_station_window(self._fallback, **kwargs)
            raise

    def find_recovery_station_window(self, **kwargs) -> list[CandidateStation]:
        """Search only the secondary provider after deterministic planning fails."""
        candidates = _find_station_window(self._fallback, **kwargs)
        if candidates:
            return candidates
        raise StationProviderError(
            "Station web search completed without a grounded candidate in the recovery window."
        )


class FixtureStationDataService:
    def __init__(self, fixtures: list[StationSnapshotFixture] | None = None):
        self._stations = fixtures if fixtures is not None else load_station_fixtures()

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
        """Find and filter compatible stations along the route corridor."""
        if not polyline:
            return []

        candidates: list[CandidateStation] = []
        now = datetime.now(UTC)

        latitude_padding = max_corridor_buffer_km / 111.0
        mean_lat = sum(point[0] for point in polyline) / len(polyline)
        longitude_padding = max_corridor_buffer_km / max(20.0, 111.0 * math.cos(math.radians(mean_lat)))
        min_lat = min(point[0] for point in polyline) - latitude_padding
        max_lat = max(point[0] for point in polyline) + latitude_padding
        min_lon = min(point[1] for point in polyline) - longitude_padding
        max_lon = max(point[1] for point in polyline) + longitude_padding

        for st in self._stations:
            # 1. Filter status
            if st.status != "OPERATIONAL":
                continue

            # 2. Check bounding box
            if not (min_lat <= st.lat <= max_lat and min_lon <= st.lon <= max_lon):
                continue

            # 3. Filter connector compatibility
            if required_connector and required_connector not in st.connector_types:
                continue

            # 4. Calculate min distance to polyline
            min_dist_to_route = float("inf")
            for pt in polyline:
                d = haversine_distance_km(st.lat, st.lon, pt[0], pt[1])
                if d < min_dist_to_route:
                    min_dist_to_route = d

            if min_dist_to_route > max_corridor_buffer_km:
                continue

            # 5. Detour calculation (estimate detour roundtrip)
            detour_dist_km = round(min_dist_to_route * 2.0, 2)
            detour_dur_min = round((detour_dist_km / 40.0) * 60.0, 1)  # urban detour speed ~40km/h

            if detour_dur_min > max_detour_min:
                continue

            # 6. Freshness calculation
            ts = now
            try:
                ts = datetime.fromisoformat(st.snapshot_timestamp.replace("Z", "+00:00"))
                age_hours = (now - ts).total_seconds() / 3600.0
                freshness: Literal["FRESH", "STALE"] = "FRESH" if age_hours <= 24.0 else "STALE"
            except (TypeError, ValueError):
                # Unknown freshness is never trusted as live availability.
                freshness = "STALE"

            if total_route_distance_km is not None and len(polyline) > 1:
                cumulative = [0.0]
                for start, end in zip(polyline, polyline[1:]):
                    cumulative.append(cumulative[-1] + haversine_distance_km(start[0], start[1], end[0], end[1]))
                nearest_index = min(
                    range(len(polyline)),
                    key=lambda index: haversine_distance_km(st.lat, st.lon, polyline[index][0], polyline[index][1]),
                )
                geometry_length = cumulative[-1]
                if geometry_length <= 0:
                    continue
                dist_from_orig = (cumulative[nearest_index] / geometry_length) * total_route_distance_km
                # Stations at/beyond either endpoint are not charging stops on this trip.
                if dist_from_orig <= 0 or dist_from_orig >= total_route_distance_km:
                    continue
            else:
                dist_from_orig = haversine_distance_km(origin_lat, origin_lng, st.lat, st.lon)

            candidates.append(
                CandidateStation(
                    station_id=st.id,
                    name=st.name,
                    lat=st.lat,
                    lon=st.lon,
                    address=st.address,
                    connector_types=st.connector_types,
                    max_power_kw=st.max_power_kw,
                    detour_distance_km=detour_dist_km,
                    detour_duration_min=detour_dur_min,
                    freshness=freshness,
                    distance_from_origin_km=round(dist_from_orig, 2),
                    connector_standard=st.connector_types[0] if st.connector_types else "",
                    station_status="ACTIVE",
                    provenance=DataProvenance(
                        source="TEST_FIXTURE",
                        source_url="test://stations",
                        retrieved_at=now,
                        source_updated_at=ts,
                        version="test-v1",
                    ),
                )
            )

        # Sort candidates chronologically along the trip from origin to destination
        candidates.sort(key=lambda s: s.distance_from_origin_km)
        return candidates

    def find_station_window(self, **kwargs) -> list[CandidateStation]:
        connectors = tuple(item.upper() for item in kwargs["compatible_connectors"])
        merged: dict[str, CandidateStation] = {}
        for connector in connectors:
            for station in self.find_corridor_stations(
                polyline=kwargs["polyline"],
                origin_lat=kwargs["origin_lat"],
                origin_lng=kwargs["origin_lng"],
                dest_lat=kwargs["dest_lat"],
                dest_lng=kwargs["dest_lng"],
                max_corridor_buffer_km=kwargs["max_corridor_buffer_km"],
                max_detour_min=kwargs["max_detour_min"],
                required_connector=connector,
                total_route_distance_km=kwargs["total_route_distance_km"],
                origin_name=kwargs.get("origin_name", "Origin"),
                dest_name=kwargs.get("dest_name", "Destination"),
            ):
                if _station_in_window(station, kwargs):
                    merged.setdefault(station.station_id, station)
        return _rank_window_candidates(
            list(merged.values()),
            kwargs["progress_end_km"],
        )[: kwargs.get("target_candidate_count", 8)]


class VinFastStationDataService:
    """Official VinFast/V-GREEN public locator adapter.

    The versioned bulk dataset is used for spatial filtering. Only shortlisted
    corridor stations are enriched through get-locator/{entity_id}.
    """

    _process_detail_cache_lock = Lock()
    _process_detail_fetch_lock = Lock()
    _process_detail_cache: dict[tuple[str, str], tuple[float, dict]] = {}

    def __init__(
        self,
        *,
        meta_url: str = "https://static-cms-prod.vinfastauto.com/locators/locators-meta.json",
        dataset_base_url: str = "https://static-cms-prod.vinfastauto.com/locators",
        detail_base_url: str = "https://vinfastauto.com/vn_vi/get-locator",
        timeout_seconds: float = 15.0,
        metadata_ttl_seconds: float = 300.0,
        max_detail_candidates: int = 36,
        min_request_interval_seconds: float = 0.05,
    ):
        self._meta_url = meta_url
        self._dataset_base_url = dataset_base_url.rstrip("/")
        self._detail_base_url = detail_base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._metadata_ttl_seconds = metadata_ttl_seconds
        self._max_detail_candidates = max(4, min(max_detail_candidates, 60))
        self._min_request_interval_seconds = max(0.0, min_request_interval_seconds)
        self._generation: str | None = None
        self._summaries: list[dict] = []
        self._dataset_retrieved_at: datetime | None = None
        self._dataset_source_updated_at: datetime | None = None
        self._last_meta_check_monotonic = 0.0
        self._detail_cache: dict[str, tuple[float, dict]] = {}
        self._detail_cache_lock = Lock()
        # Serialize cache-miss resolution so concurrent planning requests do
        # not issue duplicate upstream station-detail calls.
        self._detail_fetch_lock = Lock()

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
        if not polyline:
            return []

        self._refresh_dataset_if_needed()
        coarse = self._find_coarse_candidates(
            polyline=polyline,
            max_corridor_buffer_km=max_corridor_buffer_km,
            max_detour_min=max_detour_min,
        )
        if total_route_distance_km is not None and coarse:
            geometry_distance_km = _polyline_distance_km(polyline)
            if geometry_distance_km > 0:
                scale = total_route_distance_km / geometry_distance_km
                for item in coarse:
                    item["distance_from_origin_km"] *= scale
        shortlisted = self._distribute_candidates_along_route(coarse)
        details = self._fetch_details([item["entity_id"] for item in shortlisted])

        candidates: list[CandidateStation] = []
        for item in shortlisted:
            detail = details.get(item["entity_id"])
            if detail is None:
                continue
            parsed = self._parse_detail(item, detail, required_connector)
            if parsed is not None:
                candidates.append(parsed)

        candidates.sort(key=lambda station: station.distance_from_origin_km)
        return candidates

    def find_station_window(self, **kwargs) -> list[CandidateStation]:
        polyline = kwargs["polyline"]
        if not polyline:
            return []
        self._refresh_dataset_if_needed()
        coarse = self._find_coarse_candidates(
            polyline=polyline,
            max_corridor_buffer_km=kwargs["max_corridor_buffer_km"],
            max_detour_min=kwargs["max_detour_min"],
        )
        geometry_distance_km = _polyline_distance_km(polyline)
        total_route_distance_km = kwargs["total_route_distance_km"]
        if geometry_distance_km > 0:
            scale = total_route_distance_km / geometry_distance_km
            for item in coarse:
                item["distance_from_origin_km"] *= scale

        start = kwargs["progress_start_km"]
        end = kwargs["progress_end_km"]
        origin_radius = kwargs.get("origin_radius_km")
        eligible = []
        for item in coarse:
            in_progress_window = start <= item["distance_from_origin_km"] <= end
            in_origin_radius = bool(
                origin_radius is not None
                and haversine_distance_km(
                    kwargs["origin_lat"],
                    kwargs["origin_lng"],
                    item["lat"],
                    item["lon"],
                )
                <= origin_radius
            )
            if in_progress_window or in_origin_radius:
                eligible.append(item)

        eligible.sort(
            key=lambda item: (
                item["status"] != "ACTIVE",
                -item["distance_from_origin_km"],
                item["distance_to_route_km"],
            )
        )
        max_details = max(1, min(int(kwargs.get("max_detail_candidates", 48)), 96))
        target = max(1, min(int(kwargs.get("target_candidate_count", 8)), 24))
        connectors = tuple(item.upper() for item in kwargs["compatible_connectors"])
        accepted: dict[str, CandidateStation] = {}
        for offset in range(0, min(len(eligible), max_details), 8):
            batch = eligible[offset : min(offset + 8, max_details)]
            details = self._fetch_details([item["entity_id"] for item in batch])
            for item in batch:
                detail = details.get(item["entity_id"])
                if detail is None:
                    continue
                for connector in connectors:
                    parsed = self._parse_detail(item, detail, connector)
                    if parsed is not None:
                        accepted.setdefault(parsed.station_id, parsed)
                        break
            if len(accepted) >= target:
                break
        return _rank_window_candidates(list(accepted.values()), end)

    def _refresh_dataset_if_needed(self) -> None:
        now_monotonic = time.monotonic()
        if self._summaries and now_monotonic - self._last_meta_check_monotonic < self._metadata_ttl_seconds:
            return

        headers = {"Accept": "application/json", "User-Agent": "ai-ev-agent/1.0"}
        try:
            with httpx.Client(timeout=self._timeout_seconds, follow_redirects=True, headers=headers) as client:
                meta_response = client.get(self._meta_url)
                meta_response.raise_for_status()
                metadata = meta_response.json()
                generation = str(metadata["generation"])
                filename = str(metadata["full"])

                if self._summaries and generation == self._generation:
                    self._last_meta_check_monotonic = now_monotonic
                    return

                dataset_url = f"{self._dataset_base_url}/{filename}"
                dataset_response = client.get(dataset_url)
                dataset_response.raise_for_status()
                payload = dataset_response.json()
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            if self._summaries:
                self._last_meta_check_monotonic = now_monotonic
                return
            raise StationProviderError("VinFast locator dataset is unavailable.") from exc

        records = payload.get("data")
        if not isinstance(records, list):
            raise StationProviderError("VinFast locator dataset has an invalid schema.")

        summaries: list[dict] = []
        for record in records:
            if not isinstance(record, dict) or record.get("category_slug") != "car_charging_station":
                continue
            if record.get("charging_publish") is not True or str(record.get("access_type", "")).lower() != "public":
                continue
            status = str(record.get("charging_status", "")).upper()
            if status not in {"ACTIVE", "BUSY"}:
                continue
            try:
                summaries.append(
                    {
                        "entity_id": str(record["entity_id"]),
                        "station_id": str(record.get("store_id") or record.get("code") or record["entity_id"]),
                        "name": str(record["name"]),
                        "address": str(record.get("address", "")),
                        "lat": float(record["lat"]),
                        "lon": float(record["lng"]),
                        "status": status,
                        "parking_fee": record.get("parking_fee"),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue

        if not summaries:
            raise StationProviderError("VinFast locator dataset contains no usable public car chargers.")

        self._generation = generation
        self._summaries = summaries
        self._dataset_retrieved_at = datetime.now(UTC)
        self._dataset_source_updated_at = _parse_http_datetime(dataset_response.headers.get("last-modified"))
        self._last_meta_check_monotonic = now_monotonic
        with self._detail_cache_lock:
            self._detail_cache.clear()

    def _find_coarse_candidates(
        self,
        *,
        polyline: list[list[float]],
        max_corridor_buffer_km: float,
        max_detour_min: float,
    ) -> list[dict]:
        sampled = _sample_route_with_progress(polyline, 300)
        latitude_padding = max_corridor_buffer_km / 111.0
        mean_lat = sum(point[0] for point in polyline) / len(polyline)
        longitude_padding = max_corridor_buffer_km / max(20.0, 111.0 * math.cos(math.radians(mean_lat)))
        min_lat = min(point[0] for point in polyline) - latitude_padding
        max_lat = max(point[0] for point in polyline) + latitude_padding
        min_lon = min(point[1] for point in polyline) - longitude_padding
        max_lon = max(point[1] for point in polyline) + longitude_padding

        candidates: list[dict] = []
        for summary in self._summaries:
            if not (min_lat <= summary["lat"] <= max_lat and min_lon <= summary["lon"] <= max_lon):
                continue

            nearest = min(
                sampled,
                key=lambda route_point: haversine_distance_km(
                    summary["lat"], summary["lon"], route_point[0], route_point[1]
                ),
            )
            distance_to_route = haversine_distance_km(summary["lat"], summary["lon"], nearest[0], nearest[1])
            if distance_to_route > max_corridor_buffer_km:
                continue

            detour_distance_km = distance_to_route * 2.0
            detour_duration_min = detour_distance_km / 40.0 * 60.0
            if detour_duration_min > max_detour_min:
                continue

            candidates.append(
                {
                    **summary,
                    "distance_to_route_km": distance_to_route,
                    "distance_from_origin_km": nearest[2],
                    "detour_distance_km": detour_distance_km,
                    "detour_duration_min": detour_duration_min,
                }
            )
        return candidates

    def _distribute_candidates_along_route(self, candidates: list[dict]) -> list[dict]:
        if len(candidates) <= self._max_detail_candidates:
            return sorted(candidates, key=lambda item: item["distance_from_origin_km"])

        # A fixed "three stations per 40 km" quota loses reachable chargers on
        # short, dense urban routes. Reserve part of the detail-call budget for
        # the first 10 km (including stations whose nearest route point is the
        # origin), then distribute the remainder along the complete route.
        selected: list[dict] = []
        selected_ids: set[str] = set()

        def add(item: dict) -> None:
            entity_id = item["entity_id"]
            if entity_id not in selected_ids and len(selected) < self._max_detail_candidates:
                selected.append(item)
                selected_ids.add(entity_id)

        origin_quota = max(8, self._max_detail_candidates // 3)
        origin_candidates = sorted(
            (item for item in candidates if item["distance_from_origin_km"] <= 10.0),
            key=lambda item: (
                item["status"] != "ACTIVE",
                item["distance_to_route_km"],
                item["distance_from_origin_km"],
            ),
        )
        for item in origin_candidates[:origin_quota]:
            add(item)

        max_progress = max(item["distance_from_origin_km"] for item in candidates)
        target_bucket_count = max(1, self._max_detail_candidates - len(selected))
        bucket_width_km = max(5.0, max_progress / target_bucket_count)
        buckets: dict[int, list[dict]] = {}
        for candidate in candidates:
            bucket = int(candidate["distance_from_origin_km"] // bucket_width_km)
            buckets.setdefault(bucket, []).append(candidate)
        for items in buckets.values():
            items.sort(
                key=lambda item: (
                    item["status"] != "ACTIVE",
                    item["distance_to_route_km"],
                    item["distance_from_origin_km"],
                )
            )

        rank = 0
        while len(selected) < self._max_detail_candidates:
            added = False
            for bucket in sorted(buckets):
                items = buckets[bucket]
                if rank < len(items):
                    before = len(selected)
                    add(items[rank])
                    added = added or len(selected) > before
                if len(selected) >= self._max_detail_candidates:
                    break
            if not added:
                break
            rank += 1

        if len(selected) < self._max_detail_candidates:
            for item in sorted(
                candidates,
                key=lambda candidate: (
                    candidate["status"] != "ACTIVE",
                    candidate["distance_to_route_km"],
                    candidate["distance_from_origin_km"],
                ),
            ):
                add(item)

        return sorted(selected, key=lambda item: item["distance_from_origin_km"])

    def _fetch_details(self, entity_ids: list[str]) -> dict[str, dict]:
        with self._process_detail_fetch_lock:
            with self._detail_fetch_lock:
                return self._fetch_details_locked(entity_ids)

    def _fetch_details_locked(self, entity_ids: list[str]) -> dict[str, dict]:
        results: dict[str, dict] = {}
        now_monotonic = time.monotonic()
        missing: list[str] = []
        last_provider_error: StationProviderError | None = None
        # A station can appear in overlapping route/window batches. Preserve
        # first-seen order but never fetch the same entity twice per call.
        unique_entity_ids = list(dict.fromkeys(entity_ids))
        with self._detail_cache_lock:
            for entity_id in unique_entity_ids:
                cached = self._detail_cache.get(entity_id)
                if cached is None:
                    with self._process_detail_cache_lock:
                        cached = self._process_detail_cache.get((self._detail_base_url, entity_id))
                    if cached is not None:
                        self._detail_cache[entity_id] = cached
                if cached and now_monotonic - cached[0] < 300.0:
                    results[entity_id] = cached[1]
                else:
                    missing.append(entity_id)

        if missing:
            browser_headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
                ),
            }
            with httpx.Client(
                timeout=self._timeout_seconds,
                follow_redirects=True,
                headers=browser_headers,
            ) as client:
                # VinFast issues its public edge/session cookie on the locator
                # page before XHR detail calls. The warm-up response itself may
                # be an edge challenge; the cookie is still required downstream.
                try:
                    client.get("https://vinfastauto.com/vn_vi/tim-kiem-showroom-tram-sac")
                except httpx.HTTPError:
                    pass

                # Sequential detail fetching with request interval pacing to prevent WAF anti-bot rate-limit triggers
                for index, entity_id in enumerate(missing):
                    if index > 0 and self._min_request_interval_seconds > 0:
                        time.sleep(self._min_request_interval_seconds)
                    try:
                        payload = self._fetch_one_detail(entity_id, client)
                        results[entity_id] = payload
                        with self._detail_cache_lock:
                            self._detail_cache[entity_id] = (now_monotonic, payload)
                        with self._process_detail_cache_lock:
                            self._process_detail_cache[(self._detail_base_url, entity_id)] = (
                                now_monotonic,
                                payload,
                            )
                    except StationProviderError as exc:
                        last_provider_error = exc
                        continue

        if unique_entity_ids and not results:
            if last_provider_error is not None:
                raise last_provider_error
            raise StationProviderError("VinFast station detail endpoint is unavailable.")
        return results

    def _fetch_one_detail(self, entity_id: str, client: httpx.Client | None = None) -> dict:
        request_client = client or httpx
        try:
            response = request_client.get(
                f"{self._detail_base_url}/{entity_id}",
                timeout=self._timeout_seconds,
                follow_redirects=True,
                headers={
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
                    ),
                    "Referer": "https://vinfastauto.com/vn_vi/tim-kiem-showroom-tram-sac",
                    "X-Requested-With": "XMLHttpRequest",
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "same-origin",
                },
            )
            content_type = response.headers.get("content-type", "").lower()
            logger.info(
                f"[VINFAST_API_RESPONSE] entity_id={entity_id} status={response.status_code} content_type={content_type}"
            )

            if response.status_code in {401, 403}:
                # Cloudflare may reject httpx's TLS/client fingerprint while
                # allowing the same public endpoint through urllib. Retry
                # once with the stdlib transport before surfacing WAF denial.
                if request_client is httpx or isinstance(request_client, httpx.Client):
                    try:
                        return self._fetch_one_detail_via_urllib(entity_id)
                    except StationProviderError:
                        pass
                logger.warning(
                    f"[WAF_REJECTED] entity_id={entity_id} status={response.status_code} content_type={content_type} reason=Anti-bot WAF layer 403"
                )
                raise VinFastAccessDeniedError("VinFast request was blocked by the upstream anti-bot/WAF layer.")
            if response.status_code != 200:
                logger.warning(
                    f"[WAF_REJECTED] entity_id={entity_id} status={response.status_code} content_type={content_type} reason=HTTP status {response.status_code}"
                )
                raise StationProviderError(f"VinFast API failed with status {response.status_code}.")

            text_strip = response.text.strip()
            if "text/html" in content_type or text_strip.startswith("<") or "::IM_UNDER_ATTACK_BOX::" in text_strip:
                logger.warning(
                    f"[WAF_REJECTED] entity_id={entity_id} status={response.status_code} content_type={content_type} reason=HTML challenge returned"
                )
                raise VinFastAccessDeniedError("VinFast request was blocked by the upstream anti-bot/WAF layer.")

            try:
                payload = response.json()
            except (ValueError, TypeError) as exc:
                logger.warning(
                    f"[WAF_REJECTED] entity_id={entity_id} status={response.status_code} content_type={content_type} reason=Invalid non-JSON content"
                )
                raise StationProviderError("VinFast API returned invalid non-JSON content.") from exc

            if not isinstance(payload, dict):
                raise ValueError("response payload is not an object")
            # Prefer the API envelope's station object, while tolerating the
            # already-unwrapped shape used by some gateway/cache responses.
            detail = payload.get("data")
            if isinstance(detail, dict):
                return detail
            if any(key in payload for key in ("evses", "id", "station_id", "charging_status")):
                return payload
            raise ValueError("missing data")
        except StationProviderError:
            raise
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            logger.warning(f"[VINFAST_API_ERROR] entity_id={entity_id} error={exc}")
            raise StationProviderError(f"VinFast station {entity_id} detail is unavailable.") from exc

    def _fetch_one_detail_via_urllib(self, entity_id: str) -> dict:
        request = urllib.request.Request(
            f"{self._detail_base_url}/{entity_id}",
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
                ),
                "Referer": "https://vinfastauto.com/vn_vi/tim-kiem-showroom-tram-sac",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read())
        except Exception as exc:
            raise StationProviderError("VinFast urllib detail request failed.") from exc
        if not isinstance(payload, dict):
            raise StationProviderError("VinFast API returned an invalid detail payload.")
        detail = payload.get("data")
        if isinstance(detail, dict):
            return detail
        if any(key in payload for key in ("evses", "id", "station_id", "charging_status")):
            return payload
        raise StationProviderError("VinFast API detail payload is missing data.")

    def _parse_detail(self, summary: dict, detail: dict, required_connector: str) -> CandidateStation | None:
        entity_id = summary.get("entity_id", "unknown")
        # The locator endpoint has returned both shapes over time:
        #   {"charging_status": ..., "data": {...}}
        # and the inner station object itself.  `_fetch_one_detail` historically
        # unwraps `data`, so accepting both here is required for production
        # responses as well as callers/tests that pass the raw payload.
        nested = detail.get("data") if isinstance(detail.get("data"), dict) else detail
        if not isinstance(nested, dict) or not nested:
            logger.info(f"[BUSINESS_REJECTION] entity_id={entity_id} reason=missing_nested_data")
            return None
        depot_status = str((nested.get("extra_data") or {}).get("depot_status", "")).upper()
        charging_status = str(
            detail.get("charging_status") or nested.get("charging_status") or summary.get("status", "")
        ).upper()
        station_status = charging_status

        if charging_status not in {"ACTIVE", "BUSY"} or depot_status in {
            "MAINTAINING",
            "INACTIVE",
            "UNAVAILABLE",
            "OUTOFORDER",
            "BLOCKED",
        }:
            logger.info(
                f"[BUSINESS_REJECTION] entity_id={entity_id} charging_status={charging_status} depot_status={depot_status} reason=inactive_or_maintenance"
            )
            return None

        compatible: list[tuple[str, str, float, datetime | None]] = []
        evses = nested.get("evses")
        if not isinstance(evses, list):
            logger.info(
                f"[BUSINESS_REJECTION] entity_id={entity_id} charging_status={charging_status} depot_status={depot_status} reason=missing_evses"
            )
            return None
        for evse in evses:
            if not isinstance(evse, dict):
                continue
            connectors = evse.get("connectors")
            if not isinstance(connectors, list):
                continue
            for connector in connectors:
                if not isinstance(connector, dict):
                    continue
                raw_standard = str(connector.get("standard", ""))
                normalized = _normalize_connector(raw_standard)
                if required_connector and normalized != required_connector.upper():
                    continue
                try:
                    power_kw = float(connector["max_electric_power"]) / 1000.0
                except (KeyError, TypeError, ValueError):
                    continue
                if power_kw <= 0:
                    continue
                compatible.append(
                    (normalized, raw_standard, power_kw, _parse_iso_datetime(connector.get("last_updated")))
                )

        if not compatible:
            logger.info(
                f"[BUSINESS_REJECTION] entity_id={entity_id} charging_status={charging_status} depot_status={depot_status} reason=no_compatible_connector_{required_connector}"
            )
            return None

        logger.info(
            f"[BUSINESS_ACCEPTED] entity_id={entity_id} charging_status={charging_status} depot_status={depot_status} connector={required_connector}"
        )

        best_power = max(item[2] for item in compatible)
        best = next(item for item in compatible if item[2] == best_power)
        port_count = sum(1 for item in compatible if item[0] == best[0] and item[2] == best_power)
        station_updated_at = _parse_iso_datetime(nested.get("last_updated"))
        retrieved_at = datetime.now(UTC)
        source_updated_at = station_updated_at or self._dataset_source_updated_at
        age_hours = (
            (retrieved_at - source_updated_at).total_seconds() / 3600.0
            if source_updated_at is not None
            else float("inf")
        )

        nested_parking_fee = (nested.get("extra_data") or {}).get("parking_fee")
        summary_fee = summary.get("parking_fee")
        parking_fee = (
            bool(nested_parking_fee or summary_fee)
            if nested_parking_fee is not None or summary_fee is not None
            else None
        )

        return CandidateStation(
            station_id=str(nested.get("id") or summary["station_id"]),
            name=str(nested.get("name") or summary["name"]),
            lat=summary["lat"],
            lon=summary["lon"],
            address=str(nested.get("address") or summary["address"]),
            connector_types=[best[0]],
            max_power_kw=round(best_power, 1),
            detour_distance_km=round(summary["detour_distance_km"], 2),
            detour_duration_min=round(summary["detour_duration_min"], 1),
            freshness="FRESH" if age_hours <= 24.0 else "STALE",
            distance_from_origin_km=round(summary["distance_from_origin_km"], 2),
            connector_standard=best[1],
            port_count=max(1, port_count),
            station_status=station_status,
            opening_24_7=(nested.get("opening_times") or {}).get("twentyfourseven"),
            access_type=str(nested.get("access_type") or detail.get("access_type") or "Public"),
            parking_fee=parking_fee,
            station_updated_at=station_updated_at,
            provenance=DataProvenance(
                source="VINFAST_OFFICIAL",
                source_url=f"{self._detail_base_url}/{summary['entity_id']}",
                retrieved_at=retrieved_at,
                source_updated_at=source_updated_at,
                version=self._generation,
            ),
        )


def _normalize_connector(standard: str) -> str:
    normalized = standard.upper()
    if "COMBO" in normalized or "CCS" in normalized:
        return "CCS2"
    if "62196_T2" in normalized or "TYPE_2" in normalized:
        return "TYPE2"
    return normalized


def _raise_for_station_http_status(response: httpx.Response, *, resource: str) -> None:
    status = response.status_code
    if status in {401, 403}:
        raise StationProviderError(
            f"VinFast {resource} access was denied.",
            code="PROVIDER_ACCESS_DENIED",
            http_status=status,
            retryable=False,
        )
    if status == 429:
        raise StationProviderError(
            f"VinFast {resource} was rate limited.",
            code="PROVIDER_RATE_LIMITED",
            http_status=status,
            retryable=False,
            retry_after_seconds=_station_retry_after_seconds(response.headers),
        )
    if status == 404:
        raise StationProviderError(
            f"VinFast {resource} was not found.",
            code="PROVIDER_ENTITY_NOT_FOUND",
            http_status=status,
            retryable=False,
        )
    if status >= 500:
        raise StationProviderError(
            f"VinFast {resource} is temporarily unavailable.",
            code="PROVIDER_TRANSIENT_ERROR",
            http_status=status,
            retryable=True,
        )
    if status >= 400:
        raise StationProviderError(
            f"VinFast {resource} rejected the request.",
            code="PROVIDER_REQUEST_REJECTED",
            http_status=status,
            retryable=False,
        )


def _station_retry_after_seconds(headers: object) -> float | None:
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return None
    raw = getter("Retry-After")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


def _find_station_window(service: StationService, **kwargs) -> list[CandidateStation]:
    finder = getattr(service, "find_station_window", None)
    if callable(finder):
        return finder(**kwargs)

    merged: dict[str, CandidateStation] = {}
    for connector in kwargs["compatible_connectors"]:
        stations = service.find_corridor_stations(
            polyline=kwargs["polyline"],
            origin_lat=kwargs["origin_lat"],
            origin_lng=kwargs["origin_lng"],
            dest_lat=kwargs["dest_lat"],
            dest_lng=kwargs["dest_lng"],
            max_corridor_buffer_km=kwargs["max_corridor_buffer_km"],
            max_detour_min=kwargs["max_detour_min"],
            required_connector=connector,
            total_route_distance_km=kwargs["total_route_distance_km"],
            origin_name=kwargs.get("origin_name", "Origin"),
            dest_name=kwargs.get("dest_name", "Destination"),
        )
        for station in stations:
            if _station_in_window(station, kwargs):
                merged.setdefault(station.station_id, station)
    return _rank_window_candidates(
        list(merged.values()),
        kwargs["progress_end_km"],
    )[: max(1, int(kwargs.get("target_candidate_count", 8)))]


def _station_in_window(station: CandidateStation, options: dict) -> bool:
    progress = station.distance_from_origin_km
    if options["progress_start_km"] <= progress <= options["progress_end_km"]:
        return True
    origin_radius = options.get("origin_radius_km")
    if origin_radius is None:
        return False
    return (
        haversine_distance_km(
            options["origin_lat"],
            options["origin_lng"],
            station.lat,
            station.lon,
        )
        <= origin_radius
    )


def _rank_window_candidates(
    candidates: list[CandidateStation],
    progress_end_km: float,
) -> list[CandidateStation]:
    return sorted(
        candidates,
        key=lambda station: (
            station.station_status != "ACTIVE",
            abs(progress_end_km - station.distance_from_origin_km),
            station.detour_distance_km,
            -station.max_power_kw,
            station.station_id,
        ),
    )


def _sample_route_with_progress(polyline: list[list[float]], limit: int) -> list[tuple[float, float, float]]:
    cumulative: list[float] = [0.0]
    for previous, current in zip(polyline, polyline[1:]):
        cumulative.append(cumulative[-1] + haversine_distance_km(previous[0], previous[1], current[0], current[1]))
    if len(polyline) <= limit:
        indexes = range(len(polyline))
    else:
        indexes = sorted({round(index * (len(polyline) - 1) / (limit - 1)) for index in range(limit)})
    return [(polyline[index][0], polyline[index][1], cumulative[index]) for index in indexes]


def _polyline_distance_km(polyline: list[list[float]]) -> float:
    return sum(
        haversine_distance_km(previous[0], previous[1], current[0], current[1])
        for previous, current in zip(polyline, polyline[1:])
    )


def _parse_iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _parse_http_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(value).astimezone(UTC)
    except (TypeError, ValueError):
        return None


# Backward-compatible fixture service. Runtime wiring explicitly selects the
# live adapter outside APP_ENV=test.
StationDataService = FixtureStationDataService
