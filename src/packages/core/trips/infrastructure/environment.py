from __future__ import annotations

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Protocol

import httpx

from src.packages.contracts.trips import DataProvenance, EnvironmentSnapshot

logger = logging.getLogger(__name__)


class EnvironmentProviderError(RuntimeError):
    pass


class EnvironmentProvider(Protocol):
    def get_snapshot(
        self,
        polyline: list[list[float]],
        *,
        fallback_temperature_c: float | None = None,
    ) -> EnvironmentSnapshot: ...


@dataclass(frozen=True)
class StaticEnvironmentProvider:
    """Deterministic provider used only by automated tests."""

    temperature_c: float = 25.0
    precipitation_mm: float = 0.0
    wind_speed_kmh: float = 0.0

    def get_snapshot(
        self,
        polyline: list[list[float]],
        *,
        fallback_temperature_c: float | None = None,
    ) -> EnvironmentSnapshot:
        del fallback_temperature_c
        now = datetime.now(UTC)
        provenance = DataProvenance(
            source="TEST_FIXTURE",
            source_url="test://environment",
            retrieved_at=now,
            source_updated_at=now,
            version="test-v1",
        )
        return EnvironmentSnapshot(
            temperature_c=self.temperature_c,
            precipitation_mm=self.precipitation_mm,
            wind_speed_kmh=self.wind_speed_kmh,
            elevation_gain_m=0.0,
            elevation_loss_m=0.0,
            weather_provenance=provenance,
            elevation_provenance=provenance,
        )


class OpenMeteoEnvironmentProvider:
    def __init__(
        self,
        *,
        weather_base_url: str = "https://api.open-meteo.com/v1/forecast",
        elevation_base_url: str = "https://api.open-meteo.com/v1/elevation",
        timeout_seconds: float = 8.0,
        elevation_sample_limit: int = 80,
        max_retries: int = 2,
        retry_base_delay_seconds: float = 0.5,
        cache_ttl_seconds: float = 10800.0,
        fallback_enabled: bool = True,
        fallback_consumption_margin_percent: float = 20.0,
        cached_consumption_margin_percent: float = 5.0,
        search_fallback_provider: EnvironmentProvider | None = None,
    ):
        self._weather_base_url = weather_base_url
        self._elevation_base_url = elevation_base_url
        self._timeout_seconds = timeout_seconds
        self._elevation_sample_limit = max(2, min(elevation_sample_limit, 100))
        self._max_retries = max(0, max_retries)
        self._retry_base_delay_seconds = max(0.0, retry_base_delay_seconds)
        self._cache_ttl_seconds = max(0.0, cache_ttl_seconds)
        self._fallback_enabled = fallback_enabled
        self._fallback_consumption_margin_percent = max(
            0.0, fallback_consumption_margin_percent
        )
        self._cached_consumption_margin_percent = max(
            0.0, cached_consumption_margin_percent
        )
        self._search_fallback_provider = search_fallback_provider
        self._snapshot_cache: OrderedDict[
            tuple[float, ...], tuple[float, EnvironmentSnapshot]
        ] = OrderedDict()
        self._snapshot_cache_lock = Lock()

    def get_snapshot(
        self,
        polyline: list[list[float]],
        *,
        fallback_temperature_c: float | None = None,
    ) -> EnvironmentSnapshot:
        if not polyline:
            raise EnvironmentProviderError("Route geometry is required for environmental data.")

        cache_key = self._cache_key(polyline)
        try:
            snapshot = self._get_live_snapshot(polyline)
        except EnvironmentProviderError as exc:
            cached = self._get_cached_snapshot(cache_key)
            if cached is not None:
                logger.warning(
                    "Open-Meteo unavailable; using cached environment snapshot error=%s",
                    type(exc.__cause__ or exc).__name__,
                )
                return cached
            if self._search_fallback_provider is not None:
                try:
                    logger.warning(
                        "Open-Meteo unavailable; trying environment web search fallback"
                    )
                    return self._search_fallback_provider.get_snapshot(
                        polyline,
                        fallback_temperature_c=fallback_temperature_c,
                    )
                except EnvironmentProviderError as search_exc:
                    logger.warning(
                        "Environment web search fallback unavailable error=%s",
                        type(search_exc.__cause__ or search_exc).__name__,
                    )
            if not self._fallback_enabled:
                raise
            logger.warning(
                "Open-Meteo unavailable; using policy environment fallback margin_percent=%s error=%s",
                self._fallback_consumption_margin_percent,
                type(exc.__cause__ or exc).__name__,
            )
            return self._policy_fallback_snapshot(fallback_temperature_c)

        self._remember_snapshot(cache_key, snapshot)
        return snapshot

    def _get_live_snapshot(self, polyline: list[list[float]]) -> EnvironmentSnapshot:

        retrieved_at = datetime.now(UTC)
        midpoint = polyline[len(polyline) // 2]
        sampled = _sample_polyline(polyline, self._elevation_sample_limit)

        with httpx.Client(timeout=self._timeout_seconds, follow_redirects=True) as client:
            weather_payload = self._get_json(
                client,
                provider="weather",
                url=self._weather_base_url,
                params={
                    "latitude": midpoint[0],
                    "longitude": midpoint[1],
                    "current": "temperature_2m,precipitation,wind_speed_10m",
                    "timezone": "UTC",
                },
            )
            elevation_payload = self._get_json(
                client,
                provider="elevation",
                url=self._elevation_base_url,
                params={
                    "latitude": ",".join(str(point[0]) for point in sampled),
                    "longitude": ",".join(str(point[1]) for point in sampled),
                },
            )

        current = weather_payload.get("current")
        elevations = elevation_payload.get("elevation")
        if not isinstance(current, dict) or not isinstance(elevations, list) or len(elevations) != len(sampled):
            raise EnvironmentProviderError("Open-Meteo returned an invalid payload.")

        try:
            temperature_c = float(current["temperature_2m"])
            precipitation_mm = max(0.0, float(current.get("precipitation", 0.0)))
            wind_speed_kmh = max(0.0, float(current.get("wind_speed_10m", 0.0)))
            numeric_elevations = [float(value) for value in elevations]
        except (KeyError, TypeError, ValueError) as exc:
            raise EnvironmentProviderError("Open-Meteo omitted a required field.") from exc

        elevation_gain_m = 0.0
        elevation_loss_m = 0.0
        for previous, current_elevation in zip(numeric_elevations, numeric_elevations[1:]):
            delta = current_elevation - previous
            if delta > 0:
                elevation_gain_m += delta
            else:
                elevation_loss_m += abs(delta)

        weather_updated_at = _parse_open_meteo_time(current.get("time"))
        return EnvironmentSnapshot(
            temperature_c=round(temperature_c, 1),
            precipitation_mm=round(precipitation_mm, 2),
            wind_speed_kmh=round(wind_speed_kmh, 1),
            elevation_gain_m=round(elevation_gain_m, 1),
            elevation_loss_m=round(elevation_loss_m, 1),
            weather_provenance=DataProvenance(
                source="OPEN_METEO_WEATHER",
                source_url=self._weather_base_url,
                retrieved_at=retrieved_at,
                source_updated_at=weather_updated_at,
            ),
            elevation_provenance=DataProvenance(
                source="OPEN_METEO_ELEVATION",
                source_url=self._elevation_base_url,
                retrieved_at=retrieved_at,
            ),
        )

    @staticmethod
    def _cache_key(polyline: list[list[float]]) -> tuple[float, ...]:
        points = (polyline[0], polyline[len(polyline) // 2], polyline[-1])
        return tuple(round(float(value), 2) for point in points for value in point[:2])

    def _remember_snapshot(
        self, cache_key: tuple[float, ...], snapshot: EnvironmentSnapshot
    ) -> None:
        if self._cache_ttl_seconds <= 0:
            return
        with self._snapshot_cache_lock:
            self._snapshot_cache[cache_key] = (time.monotonic(), snapshot.model_copy(deep=True))
            self._snapshot_cache.move_to_end(cache_key)
            while len(self._snapshot_cache) > 256:
                self._snapshot_cache.popitem(last=False)

    def _get_cached_snapshot(
        self, cache_key: tuple[float, ...]
    ) -> EnvironmentSnapshot | None:
        if self._cache_ttl_seconds <= 0:
            return None
        with self._snapshot_cache_lock:
            cached = self._snapshot_cache.get(cache_key)
            if cached is None:
                return None
            cached_at, snapshot = cached
            if time.monotonic() - cached_at > self._cache_ttl_seconds:
                del self._snapshot_cache[cache_key]
                return None
            self._snapshot_cache.move_to_end(cache_key)
            return snapshot.model_copy(
                deep=True,
                update={
                    "status": "CACHED",
                    "is_degraded": True,
                    "consumption_margin_percent": self._cached_consumption_margin_percent,
                    "warning": (
                        "Open-Meteo tạm thời không khả dụng; kế hoạch đang dùng "
                        "snapshot môi trường gần nhất cho cùng hành lang tuyến."
                    ),
                },
            )

    def _policy_fallback_snapshot(
        self, fallback_temperature_c: float | None
    ) -> EnvironmentSnapshot:
        now = datetime.now(UTC)
        provenance = DataProvenance(
            source="POLICY_FALLBACK",
            source_url="policy://environment-fallback",
            retrieved_at=now,
            source_updated_at=now,
            version="environment-fallback-v1",
        )
        return EnvironmentSnapshot(
            temperature_c=(
                float(fallback_temperature_c)
                if fallback_temperature_c is not None
                else 25.0
            ),
            precipitation_mm=0.0,
            wind_speed_kmh=0.0,
            elevation_gain_m=0.0,
            elevation_loss_m=0.0,
            weather_provenance=provenance,
            elevation_provenance=provenance,
            status="POLICY_FALLBACK",
            is_degraded=True,
            consumption_margin_percent=self._fallback_consumption_margin_percent,
            warning=(
                "Open-Meteo không khả dụng; kế hoạch dùng giả định policy "
                "với biên tiêu hao dự phòng."
            ),
        )

    def _get_json(
        self,
        client: httpx.Client,
        *,
        provider: str,
        url: str,
        params: dict[str, object],
    ) -> object:
        attempts = self._max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                response = client.get(url, params=params)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                retryable = status_code in {408, 425, 429} or status_code >= 500
                logger.warning(
                    "Open-Meteo %s request failed status=%s attempt=%s/%s",
                    provider,
                    status_code,
                    attempt,
                    attempts,
                )
                if attempt >= attempts or not retryable:
                    raise EnvironmentProviderError(
                        f"Open-Meteo {provider} request failed with HTTP {status_code}."
                    ) from exc
                self._sleep_before_retry(attempt, exc.response.headers.get("Retry-After"))
            except httpx.RequestError as exc:
                logger.warning(
                    "Open-Meteo %s request failed error=%s attempt=%s/%s",
                    provider,
                    type(exc).__name__,
                    attempt,
                    attempts,
                )
                if attempt >= attempts:
                    raise EnvironmentProviderError(
                        f"Open-Meteo {provider} request failed with {type(exc).__name__}."
                    ) from exc
                self._sleep_before_retry(attempt)
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "Open-Meteo %s returned invalid JSON error=%s",
                    provider,
                    type(exc).__name__,
                )
                raise EnvironmentProviderError(
                    f"Open-Meteo {provider} returned invalid JSON."
                ) from exc

        raise EnvironmentProviderError(f"Open-Meteo {provider} request failed.")

    def _sleep_before_retry(self, attempt: int, retry_after: str | None = None) -> None:
        delay = self._retry_base_delay_seconds * (2 ** (attempt - 1))
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                pass
        if delay > 0:
            time.sleep(min(delay, 30.0))


def _sample_polyline(polyline: list[list[float]], limit: int) -> list[list[float]]:
    if len(polyline) <= limit:
        return polyline
    indexes = {round(index * (len(polyline) - 1) / (limit - 1)) for index in range(limit)}
    return [polyline[index] for index in sorted(indexes)]


def _parse_open_meteo_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
