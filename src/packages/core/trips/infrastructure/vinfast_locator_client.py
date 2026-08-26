from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from src.packages.core.trips.infrastructure.cache_backend import (
    CacheBackend,
    CacheBackendError,
)
from src.packages.core.trips.infrastructure.observability import metrics
from src.packages.core.trips.infrastructure.station_service import (
    ProviderCircuitBreaker,
    StationProviderError,
    _parse_http_datetime,
    _raise_for_station_http_status,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VinFastLocatorMetadata:
    generation: str
    full_filename: str
    source_url: str
    retrieved_at: datetime
    source_last_modified_at: datetime | None
    raw_payload: dict


@dataclass(frozen=True)
class VinFastBulkDataset:
    generation: str
    source_url: str
    retrieved_at: datetime
    source_last_modified_at: datetime | None
    checksum: str
    records: tuple[dict, ...]


class VinFastLocatorClient:
    """HTTP-only VinFast locator client for background ingestion/hydration."""

    def __init__(
        self,
        *,
        meta_url: str,
        dataset_base_url: str,
        detail_base_url: str,
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        access_denied_cooldown_seconds: float = 300.0,
        rate_limit_cooldown_seconds: float = 30.0,
        cache_backend: CacheBackend | None = None,
        detail_cache_ttl_seconds: float = 300.0,
    ):
        self._meta_url = meta_url
        self._dataset_base_url = dataset_base_url.rstrip("/")
        self._detail_base_url = detail_base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(0, max_retries)
        self._access_denied_cooldown_seconds = access_denied_cooldown_seconds
        self._rate_limit_cooldown_seconds = rate_limit_cooldown_seconds
        self._locator_circuit = ProviderCircuitBreaker(
            default_cooldown_seconds=access_denied_cooldown_seconds,
            cache_backend=cache_backend,
            cache_key="provider-circuit:vinfast-locator",
        )
        self._detail_circuit = ProviderCircuitBreaker(
            default_cooldown_seconds=access_denied_cooldown_seconds,
            cache_backend=cache_backend,
            cache_key="provider-circuit:vinfast-detail",
        )
        self._cache_backend = cache_backend
        self._detail_cache_ttl_seconds = max(0.0, detail_cache_ttl_seconds)

    @property
    def detail_base_url(self) -> str:
        return self._detail_base_url

    def fetch_metadata(self) -> VinFastLocatorMetadata:
        response, payload, retrieved_at = self._get_json(
            self._meta_url,
            resource="locator metadata",
            circuit=self._locator_circuit,
        )
        try:
            generation = str(payload["generation"])
            full_filename = str(payload["full"])
        except (KeyError, TypeError, ValueError) as exc:
            raise StationProviderError(
                "VinFast locator metadata has an invalid schema.",
                code="PROVIDER_INVALID_SCHEMA",
            ) from exc
        return VinFastLocatorMetadata(
            generation=generation,
            full_filename=full_filename,
            source_url=self._meta_url,
            retrieved_at=retrieved_at,
            source_last_modified_at=_parse_http_datetime(response.headers.get("last-modified")),
            raw_payload=payload,
        )

    def fetch_bulk_dataset(self, metadata: VinFastLocatorMetadata) -> VinFastBulkDataset:
        source_url = f"{self._dataset_base_url}/{metadata.full_filename}"
        response, payload, retrieved_at = self._get_json(
            source_url,
            resource="locator bulk dataset",
            circuit=self._locator_circuit,
        )
        records = payload.get("data")
        if not isinstance(records, list):
            raise StationProviderError(
                "VinFast locator bulk dataset has an invalid schema.",
                code="PROVIDER_INVALID_SCHEMA",
            )
        checksum = hashlib.sha256(response.content).hexdigest()
        return VinFastBulkDataset(
            generation=metadata.generation,
            source_url=source_url,
            retrieved_at=retrieved_at,
            source_last_modified_at=_parse_http_datetime(response.headers.get("last-modified")),
            checksum=checksum,
            records=tuple(record for record in records if isinstance(record, dict)),
        )

    def fetch_detail(
        self,
        external_id: str,
        dataset_generation: str | None = None,
    ) -> tuple[dict, datetime]:
        cache_key = (
            f"station-detail:v1:VINFAST_OFFICIAL:{external_id}:"
            f"{dataset_generation or 'unknown'}"
        )
        if self._cache_backend is not None:
            try:
                cached = self._cache_backend.get(cache_key)
                if cached is not None:
                    value = json.loads(cached.decode("utf-8"))
                    metrics.increment(
                        "station_detail_cache_hits_total", provider="VINFAST_OFFICIAL"
                    )
                    return value["detail"], datetime.fromisoformat(value["retrieved_at"])
            except (CacheBackendError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                pass
        source_url = f"{self._detail_base_url}/{external_id}"
        metrics.increment(
            "station_detail_upstream_requests_total", provider="VINFAST_OFFICIAL"
        )
        _response, payload, retrieved_at = self._get_json(
            source_url,
            resource=f"station detail {external_id}",
            circuit=self._detail_circuit,
            headers={
                "Accept": "application/json",
                "User-Agent": "ai-ev-agent/1.0",
            },
        )
        detail = payload.get("data")
        if not isinstance(detail, dict):
            raise StationProviderError(
                f"VinFast station {external_id} detail has an invalid schema.",
                code="PROVIDER_INVALID_SCHEMA",
            )
        if self._cache_backend is not None:
            try:
                self._cache_backend.set(
                    cache_key,
                    json.dumps(
                        {"detail": detail, "retrieved_at": retrieved_at.isoformat()},
                        separators=(",", ":"),
                    ).encode("utf-8"),
                    ttl_seconds=self._detail_cache_ttl_seconds,
                )
            except CacheBackendError:
                pass
        return detail, retrieved_at

    def _get_json(
        self,
        url: str,
        *,
        resource: str,
        circuit: ProviderCircuitBreaker,
        headers: dict[str, str] | None = None,
    ) -> tuple[httpx.Response, dict, datetime]:
        circuit_state = circuit.current_state()
        if circuit_state is not None:
            raise StationProviderError(
                f"VinFast {resource} provider circuit is open.",
                code=circuit_state.reason,
                retry_after_seconds=circuit_state.retry_after_seconds,
            )

        request_headers = {
            "Accept": "application/json",
            "User-Agent": "ai-ev-agent/1.0",
            **(headers or {}),
        }
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = httpx.get(
                    url,
                    timeout=self._timeout_seconds,
                    follow_redirects=True,
                    headers=request_headers,
                )
                _raise_for_station_http_status(response, resource=resource)
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("expected JSON object")
                return response, payload, datetime.now(UTC)
            except StationProviderError as exc:
                last_error = exc
                if exc.code == "PROVIDER_ACCESS_DENIED":
                    circuit.open(
                        reason=exc.code,
                        retry_after_seconds=self._access_denied_cooldown_seconds,
                    )
                    raise
                if exc.code == "PROVIDER_RATE_LIMITED":
                    circuit.open(
                        reason=exc.code,
                        retry_after_seconds=max(
                            self._rate_limit_cooldown_seconds,
                            exc.retry_after_seconds or 0.0,
                        ),
                    )
                    raise
                if not exc.retryable or attempt >= self._max_retries:
                    raise
            except (httpx.TransportError, ValueError) as exc:
                last_error = exc
                if attempt >= self._max_retries:
                    break
            time.sleep(min(3.0, 0.5 * (2**attempt)))

        logger.warning(
            "vinfast_provider_request_failed",
            extra={"provider": "VINFAST_OFFICIAL", "resource": resource},
        )
        raise StationProviderError(
            f"VinFast {resource} is unavailable after bounded retry.",
            code="PROVIDER_TRANSIENT_ERROR",
            retryable=True,
        ) from last_error
