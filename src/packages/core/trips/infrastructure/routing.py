from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock
from typing import Protocol

import httpx

from src.packages.core.trips.infrastructure.cache_backend import (
    CacheBackend,
    CacheBackendError,
    InMemoryCacheBackend,
)


@dataclass(frozen=True)
class RouteSegmentData:
    from_name: str
    to_name: str
    distance_km: float
    duration_min: float
    start_lat: float
    start_lng: float
    end_lat: float
    end_lng: float


@dataclass(frozen=True)
class RoutingResult:
    polyline: list[list[float]]  # [[lat, lng], ...]
    distance_km: float
    duration_min: float
    segments: list[RouteSegmentData] = field(default_factory=list)
    provider: str = "UNKNOWN"
    source_url: str = ""
    retrieved_at: datetime | None = None


class RoutingProviderError(RuntimeError):
    pass


class RoutingUnavailableError(RoutingProviderError):
    """Raised when the real routing provider cannot return a validated route."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        provider_status: str | None = None,
        retryable: bool = True,
        retry_after_seconds: float | None = None,
    ):
        super().__init__(message)
        self.http_status = http_status
        self.provider_status = provider_status
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


def route_cache_key(
    *,
    provider: str,
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    waypoints: list[tuple[float, float]] | None = None,
) -> str:
    """Return a stable, provider-scoped cache key for a route request."""
    ordered = ";".join(
        f"{lat:.6f},{lng:.6f}" for lat, lng in (waypoints or [])
    )
    waypoint_hash = hashlib.sha256(ordered.encode("utf-8")).hexdigest()[:16]
    origin = f"{origin_lat:.6f},{origin_lng:.6f}"
    destination = f"{dest_lat:.6f},{dest_lng:.6f}"
    return f"route:v1:{provider}:{origin}:{destination}:{waypoint_hash}"


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def generate_interpolated_polyline(
    lat1: float, lon1: float, lat2: float, lon2: float, num_points: int = 10
) -> list[list[float]]:
    points: list[list[float]] = []
    for i in range(num_points + 1):
        frac = i / float(num_points)
        plat = lat1 + (lat2 - lat1) * frac
        plon = lon1 + (lon2 - lon1) * frac
        points.append([round(plat, 5), round(plon, 5)])
    return points


class RoutingProvider(Protocol):
    def get_route(
        self,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        waypoints: list[tuple[float, float]] | None = None,
    ) -> RoutingResult: ...


class InMemoryRoutingProvider:
    """Deterministic routing provider for unit tests and local simulations."""

    def __init__(self, avg_speed_kmh: float = 70.0):
        self._avg_speed_kmh = avg_speed_kmh

    def get_route(
        self,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        waypoints: list[tuple[float, float]] | None = None,
    ) -> RoutingResult:
        all_stops = [(origin_lat, origin_lng)]
        if waypoints:
            all_stops.extend(waypoints)
        all_stops.append((dest_lat, dest_lng))

        total_distance = 0.0
        total_duration = 0.0
        polyline: list[list[float]] = []
        segments: list[RouteSegmentData] = []

        for i in range(len(all_stops) - 1):
            s_lat, s_lng = all_stops[i]
            e_lat, e_lng = all_stops[i + 1]
            dist = haversine_distance_km(s_lat, s_lng, e_lat, e_lng)
            # Route road curvature multiplier ~ 1.18 for realistic driving
            road_dist = dist * 1.18
            dur = (road_dist / self._avg_speed_kmh) * 60.0
            total_distance += road_dist
            total_duration += dur

            sub_poly = generate_interpolated_polyline(s_lat, s_lng, e_lat, e_lng, num_points=8)
            if polyline and sub_poly:
                polyline.extend(sub_poly[1:])
            else:
                polyline.extend(sub_poly)

            segments.append(
                RouteSegmentData(
                    from_name=f"Stop {i}",
                    to_name=f"Stop {i + 1}",
                    distance_km=round(road_dist, 2),
                    duration_min=round(dur, 1),
                    start_lat=s_lat,
                    start_lng=s_lng,
                    end_lat=e_lat,
                    end_lng=e_lng,
                )
            )

        return RoutingResult(
            polyline=polyline,
            distance_km=round(total_distance, 2),
            duration_min=round(total_duration, 1),
            segments=segments,
            provider="TEST_FIXTURE",
            source_url="test://routing",
            retrieved_at=datetime.now(UTC),
        )


def decode_polyline(encoded: str, precision: int = 5) -> list[list[float]]:
    """Decode Goong's encoded polyline into [[lat, lng], ...]."""
    if not encoded:
        return []

    coordinates: list[list[float]] = []
    index = 0
    latitude = 0
    longitude = 0
    factor = 10**precision

    while index < len(encoded):
        deltas: list[int] = []
        for _ in range(2):
            result = 0
            shift = 0
            while True:
                if index >= len(encoded):
                    raise ValueError("Goong returned a malformed encoded polyline.")
                value = ord(encoded[index]) - 63
                index += 1
                result |= (value & 0x1F) << shift
                shift += 5
                if value < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)

        latitude += deltas[0]
        longitude += deltas[1]
        coordinates.append([latitude / factor, longitude / factor])

    return coordinates


class GoongRoutingProvider:
    """Live driving routes from Goong Directions API."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://rsapi.goong.io",
        timeout_seconds: float = 8.0,
        max_retries: int = 2,
        rate_limit_cooldown_seconds: float = 30.0,
        min_request_interval_seconds: float = 0.2,
        route_cache_ttl_seconds: float = 300.0,
        cache_backend: CacheBackend | None = None,
    ):
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._rate_limit_cooldown_seconds = max(1.0, rate_limit_cooldown_seconds)
        self._rate_limited_until = 0.0
        self._rate_limit_lock = Lock()
        self._min_request_interval_seconds = max(0.0, min_request_interval_seconds)
        self._next_request_at = 0.0
        self._request_pacing_lock = Lock()
        self._route_cache_ttl_seconds = max(0.0, route_cache_ttl_seconds)
        self._cache_backend = cache_backend or InMemoryCacheBackend(max_entries=512)
        # A waypoint is a required charging stop, not merely a hint. Goong
        # normally routes within a few metres of it; reject a response that
        # silently falls back to the direct origin-destination route.
        self._waypoint_match_radius_km = 1.0

    def get_route(
        self,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        waypoints: list[tuple[float, float]] | None = None,
    ) -> RoutingResult:
        if not self._api_key:
            raise RoutingUnavailableError(
                "GOONG_API_KEY is not configured for Goong Directions."
            )

        cache_key = route_cache_key(
            provider="GOONG_DIRECTIONS",
            origin_lat=origin_lat,
            origin_lng=origin_lng,
            dest_lat=dest_lat,
            dest_lng=dest_lng,
            waypoints=waypoints,
        )
        try:
            cached = self._cache_backend.get(cache_key)
            if cached is not None:
                return _deserialize_route(cached)
        except (CacheBackendError, ValueError, TypeError, KeyError):
            pass

        with self._rate_limit_lock:
            remaining = self._rate_limited_until - time.monotonic()
        if remaining > 0:
            raise RoutingUnavailableError(
                "Goong Directions rate limit is active; retry later.",
                http_status=429,
                provider_status="RATE_LIMITED",
                retryable=True,
                retry_after_seconds=remaining,
            )

        with self._request_pacing_lock:
            wait_seconds = self._next_request_at - time.monotonic()
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            self._next_request_at = time.monotonic() + self._min_request_interval_seconds

        destinations = [*(waypoints or []), (dest_lat, dest_lng)]
        params = {
            "origin": f"{origin_lat},{origin_lng}",
            "destination": ";".join(f"{lat},{lng}" for lat, lng in destinations),
            "vehicle": "car",
            "alternatives": "false",
            "api_key": self._api_key,
        }
        last_error: Exception | None = None

        for _attempt in range(self._max_retries + 1):
            try:
                response = httpx.get(
                    f"{self._base_url}/Direction",
                    params=params,
                    timeout=self._timeout_seconds,
                    follow_redirects=True,
                )
                try:
                    data = response.json()
                except ValueError:
                    data = None
                status_code = int(getattr(response, "status_code", 200))
                if status_code >= 400:
                    provider_status = (
                        str(data.get("status"))
                        if isinstance(data, dict) and data.get("status")
                        else None
                    )
                    retryable = status_code >= 500 or status_code == 429
                    retry_after_seconds = _retry_after_seconds(getattr(response, "headers", {}))
                    if status_code == 429:
                        retry_after_seconds = max(
                            self._rate_limit_cooldown_seconds,
                            retry_after_seconds or 0.0,
                        )
                        with self._rate_limit_lock:
                            self._rate_limited_until = time.monotonic() + retry_after_seconds
                    raise RoutingUnavailableError(
                        "Goong Directions rejected the requested route.",
                        http_status=status_code,
                        provider_status=provider_status,
                        retryable=retryable,
                        retry_after_seconds=retry_after_seconds,
                    )
                routes = data.get("routes") if isinstance(data, dict) else None
                if not isinstance(routes, list) or not routes:
                    provider_status = (
                        str(data.get("status"))
                        if isinstance(data, dict) and data.get("status")
                        else None
                    )
                    if provider_status == "NOT_FOUND":
                        raise RoutingUnavailableError(
                            "Goong Directions could not route to the requested endpoint.",
                            http_status=400,
                            provider_status=provider_status,
                            retryable=False,
                        )
                    raise RoutingProviderError("Goong Directions returned no route.")

                route = routes[0]
                legs = route.get("legs") if isinstance(route, dict) else None
                encoded = route.get("overview_polyline", {}).get("points") if isinstance(route, dict) else None
                if not isinstance(legs, list) or not legs:
                    raise RoutingProviderError("Goong Directions returned no route legs.")
                if not isinstance(encoded, str):
                    raise RoutingProviderError("Goong Directions returned no route geometry.")

                distance_m = 0.0
                duration_seconds = 0.0
                route_segments: list[RouteSegmentData] = []
                stops = [(origin_lat, origin_lng), *destinations]
                for index, leg in enumerate(legs):
                    if not isinstance(leg, dict):
                        raise RoutingProviderError("Goong Directions returned a malformed route leg.")
                    leg_distance = leg.get("distance", {}).get("value")
                    leg_duration = leg.get("duration", {}).get("value")
                    if not isinstance(leg_distance, (int, float)) or leg_distance < 0:
                        raise RoutingProviderError("Goong Directions returned an invalid distance.")
                    if not isinstance(leg_duration, (int, float)) or leg_duration < 0:
                        raise RoutingProviderError("Goong Directions returned an invalid duration.")
                    distance_m += float(leg_distance)
                    duration_seconds += float(leg_duration)
                    if index < len(stops) - 1:
                        start_lat, start_lng = stops[index]
                        end_lat, end_lng = stops[index + 1]
                        route_segments.append(
                            RouteSegmentData(
                                from_name="Origin" if index == 0 else f"Stop {index}",
                                to_name=(
                                    "Destination"
                                    if index == len(stops) - 2
                                    else f"Stop {index + 1}"
                                ),
                                distance_km=round(float(leg_distance) / 1000.0, 2),
                                duration_min=round(float(leg_duration) / 60.0, 1),
                                start_lat=start_lat,
                                start_lng=start_lng,
                                end_lat=end_lat,
                                end_lng=end_lng,
                            )
                        )

                polyline = decode_polyline(encoded)
                if len(polyline) < 2 or distance_m <= 0:
                    raise RoutingProviderError("Goong Directions returned an invalid route.")
                for waypoint_lat, waypoint_lng in waypoints or []:
                    nearest_waypoint_distance = min(
                        haversine_distance_km(waypoint_lat, waypoint_lng, point[0], point[1])
                        for point in polyline
                    )
                    if nearest_waypoint_distance > self._waypoint_match_radius_km:
                        raise RoutingUnavailableError(
                            "Goong Directions returned a route that does not pass through a required charging stop.",
                            provider_status="WAYPOINT_SKIPPED",
                            retryable=False,
                        )

                distance_km = distance_m / 1000.0
                duration_min = duration_seconds / 60.0
                result = RoutingResult(
                    polyline=polyline,
                    distance_km=round(distance_km, 2),
                    duration_min=round(duration_min, 1),
                    segments=route_segments,
                    provider="GOONG_DIRECTIONS",
                    source_url=f"{self._base_url}/Direction",
                    retrieved_at=datetime.now(UTC),
                )
                try:
                    self._cache_backend.set(
                        cache_key,
                        _serialize_route(result),
                        ttl_seconds=self._route_cache_ttl_seconds,
                    )
                except CacheBackendError:
                    pass
                return result
            except RoutingUnavailableError as exc:
                if not exc.retryable or exc.http_status == 429:
                    raise
                last_error = exc
                if _attempt < self._max_retries:
                    time.sleep(min(3.0, 0.5 * (2**_attempt)))
            except Exception as exc:
                last_error = exc

        if isinstance(last_error, RoutingUnavailableError):
            raise last_error
        raise RoutingUnavailableError(
            "Goong Directions is unavailable; no synthetic route was generated."
        ) from last_error


def _retry_after_seconds(headers: object) -> float | None:
    if not isinstance(headers, dict):
        try:
            value = headers.get("Retry-After")
        except AttributeError:
            return None
    else:
        value = headers.get("Retry-After") or headers.get("retry-after")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _serialize_route(route: RoutingResult) -> bytes:
    import json

    payload = {
        "polyline": route.polyline,
        "distance_km": route.distance_km,
        "duration_min": route.duration_min,
        "segments": [segment.__dict__ for segment in route.segments],
        "provider": route.provider,
        "source_url": route.source_url,
        "retrieved_at": route.retrieved_at.isoformat() if route.retrieved_at else None,
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _deserialize_route(value: bytes) -> RoutingResult:
    import json

    payload = json.loads(value.decode("utf-8"))
    retrieved_at = payload.get("retrieved_at")
    return RoutingResult(
        polyline=payload["polyline"],
        distance_km=float(payload["distance_km"]),
        duration_min=float(payload["duration_min"]),
        segments=[RouteSegmentData(**segment) for segment in payload.get("segments", [])],
        provider=str(payload["provider"]),
        source_url=str(payload.get("source_url", "")),
        retrieved_at=datetime.fromisoformat(retrieved_at) if retrieved_at else None,
    )
