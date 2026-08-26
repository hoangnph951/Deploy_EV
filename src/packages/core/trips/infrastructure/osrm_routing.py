from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from src.packages.core.trips.infrastructure.observability import metrics
from src.packages.core.trips.infrastructure.routing import (
    RouteSegmentData,
    RoutingProviderError,
    RoutingResult,
    RoutingUnavailableError,
)


@dataclass(frozen=True)
class RoadMatrixCell:
    distance_km: float
    duration_minutes: float
    provider: str
    source_url: str
    retrieved_at: datetime


class OsrmRoutingProvider:
    """Self-hosted OSRM route and one-to-many table adapter."""

    provider_name = "OSRM"

    def __init__(
        self,
        *,
        base_url: str,
        profile: str = "driving",
        timeout_seconds: float = 15.0,
        max_retries: int = 1,
        max_table_locations: int = 100,
        client: httpx.Client | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._profile = profile.strip() or "driving"
        self._timeout_seconds = max(0.1, timeout_seconds)
        self._max_retries = max(0, max_retries)
        self._max_table_locations = max(2, max_table_locations)
        self._client = client or httpx.Client(
            timeout=self._timeout_seconds,
            follow_redirects=False,
            headers={"Accept": "application/json", "User-Agent": "ai-ev-agent/1.0"},
        )
        self._owns_client = client is None

    @property
    def profile(self) -> str:
        return self._profile

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def get_route_matrix(
        self,
        origin_lat: float,
        origin_lng: float,
        destinations: list[tuple[float, float]],
    ) -> tuple[RoadMatrixCell | None, ...]:
        if not destinations:
            return ()
        if len(destinations) + 1 > self._max_table_locations:
            raise ValueError(
                "OSRM table request exceeds the configured location limit."
            )
        coordinates = [(origin_lat, origin_lng), *destinations]
        encoded = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in coordinates)
        endpoint = f"{self._base_url}/table/v1/{self._profile}/{encoded}"
        metrics.increment("routing_matrix_requests_total", provider=self.provider_name)
        response = self._request(
            endpoint,
            params={
                "sources": "0",
                "destinations": ";".join(
                    str(index) for index in range(1, len(coordinates))
                ),
                "annotations": "distance,duration",
                "skip_waypoints": "true",
            },
        )
        data = _json_object(response)
        if data.get("code") != "Ok":
            raise RoutingProviderError(
                f"OSRM table failed with code {data.get('code', 'UNKNOWN')}."
            )
        distances = data.get("distances")
        durations = data.get("durations")
        if (
            not isinstance(distances, list)
            or len(distances) != 1
            or not isinstance(distances[0], list)
            or not isinstance(durations, list)
            or len(durations) != 1
            or not isinstance(durations[0], list)
            or len(distances[0]) != len(destinations)
            or len(durations[0]) != len(destinations)
        ):
            raise RoutingProviderError("OSRM table returned an invalid matrix shape.")

        retrieved_at = datetime.now(UTC)
        cells: list[RoadMatrixCell | None] = []
        for distance_m, duration_s in zip(distances[0], durations[0], strict=True):
            if distance_m is None or duration_s is None:
                cells.append(None)
                continue
            if (
                isinstance(distance_m, (int, float))
                and isinstance(duration_s, (int, float))
                and math.isfinite(float(distance_m))
                and math.isfinite(float(duration_s))
                and distance_m <= 0
                and duration_s >= 0
            ):
                cells.append(None)
                continue
            if (
                not isinstance(distance_m, (int, float))
                or not isinstance(duration_s, (int, float))
                or not math.isfinite(float(distance_m))
                or not math.isfinite(float(duration_s))
                or distance_m < 0
                or duration_s < 0
            ):
                raise RoutingProviderError(
                    "OSRM table returned invalid road facts: "
                    f"distance={distance_m!r}, duration={duration_s!r}."
                )
            cells.append(
                RoadMatrixCell(
                    distance_km=round(float(distance_m) / 1000.0, 3),
                    duration_minutes=round(float(duration_s) / 60.0, 3),
                    provider=self.provider_name,
                    source_url=f"{self._base_url}/table/v1/{self._profile}",
                    retrieved_at=retrieved_at,
                )
            )
        return tuple(cells)

    def get_route(
        self,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        waypoints: list[tuple[float, float]] | None = None,
    ) -> RoutingResult:
        coordinates = [
            (origin_lat, origin_lng),
            *(waypoints or []),
            (dest_lat, dest_lng),
        ]
        encoded = ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in coordinates)
        endpoint = f"{self._base_url}/route/v1/{self._profile}/{encoded}"
        metrics.increment("routing_requests_total", provider=self.provider_name)
        response = self._request(
            endpoint,
            params={
                "alternatives": "false",
                "overview": "full",
                "geometries": "geojson",
                "steps": "false",
            },
        )
        data = _json_object(response)
        routes = data.get("routes")
        if data.get("code") != "Ok" or not isinstance(routes, list) or not routes:
            raise RoutingUnavailableError(
                "OSRM could not route between the requested coordinates.",
                provider_status=str(data.get("code") or "NO_ROUTE"),
                retryable=False,
            )
        route = routes[0]
        if not isinstance(route, dict):
            raise RoutingProviderError("OSRM returned a malformed route.")
        distance_m = route.get("distance")
        duration_s = route.get("duration")
        raw_coordinates = (route.get("geometry") or {}).get("coordinates")
        if (
            not isinstance(distance_m, (int, float))
            or distance_m <= 0
            or not isinstance(duration_s, (int, float))
            or duration_s < 0
            or not isinstance(raw_coordinates, list)
            or len(raw_coordinates) < 2
        ):
            raise RoutingProviderError("OSRM returned invalid route facts.")
        polyline = [
            [float(coordinate[1]), float(coordinate[0])]
            for coordinate in raw_coordinates
            if isinstance(coordinate, list) and len(coordinate) >= 2
        ]
        if len(polyline) < 2:
            raise RoutingProviderError("OSRM returned invalid GeoJSON geometry.")

        legs = route.get("legs")
        segments: list[RouteSegmentData] = []
        if isinstance(legs, list):
            for index, leg in enumerate(legs):
                if not isinstance(leg, dict) or index >= len(coordinates) - 1:
                    continue
                leg_distance = leg.get("distance")
                leg_duration = leg.get("duration")
                if not isinstance(leg_distance, (int, float)) or not isinstance(
                    leg_duration, (int, float)
                ):
                    continue
                start_lat, start_lng = coordinates[index]
                end_lat, end_lng = coordinates[index + 1]
                segments.append(
                    RouteSegmentData(
                        from_name="Origin" if index == 0 else f"Stop {index}",
                        to_name=(
                            "Destination"
                            if index == len(coordinates) - 2
                            else f"Stop {index + 1}"
                        ),
                        distance_km=round(float(leg_distance) / 1000.0, 3),
                        duration_min=round(float(leg_duration) / 60.0, 3),
                        start_lat=start_lat,
                        start_lng=start_lng,
                        end_lat=end_lat,
                        end_lng=end_lng,
                    )
                )
        return RoutingResult(
            polyline=polyline,
            distance_km=round(float(distance_m) / 1000.0, 3),
            duration_min=round(float(duration_s) / 60.0, 3),
            segments=segments,
            provider=self.provider_name,
            source_url=f"{self._base_url}/route/v1/{self._profile}",
            retrieved_at=datetime.now(UTC),
        )

    def _request(self, url: str, *, params: dict[str, str]) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.get(url, params=params)
                if response.status_code >= 400:
                    retryable = response.status_code >= 500
                    error = RoutingUnavailableError(
                        "Self-hosted OSRM rejected the routing request.",
                        http_status=response.status_code,
                        provider_status="OSRM_HTTP_ERROR",
                        retryable=retryable,
                    )
                    if not retryable:
                        raise error
                    last_error = error
                else:
                    return response
            except RoutingUnavailableError:
                raise
            except httpx.HTTPError as exc:
                last_error = exc
            if attempt < self._max_retries:
                time.sleep(min(1.0, 0.2 * (2**attempt)))
        raise RoutingUnavailableError(
            "Self-hosted OSRM is unavailable.",
            provider_status="OSRM_UNAVAILABLE",
            retryable=True,
        ) from last_error


def _json_object(response: httpx.Response) -> dict:
    try:
        data = response.json()
    except ValueError as exc:
        raise RoutingProviderError("OSRM returned non-JSON content.") from exc
    if not isinstance(data, dict):
        raise RoutingProviderError("OSRM returned an invalid JSON payload.")
    return data
