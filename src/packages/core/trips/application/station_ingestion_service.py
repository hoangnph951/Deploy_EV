from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.packages.core.trips.application.station_catalog_repository import (
    StationCatalogRepository,
)
from src.packages.core.trips.domain.station_catalog import (
    StationConnectorData,
    StationDatasetVersion,
    StationEvseData,
    StationLocationUpsert,
)
from src.packages.core.trips.infrastructure.station_service import (
    StationProviderError,
    _normalize_connector,
    _parse_iso_datetime,
)
from src.packages.core.trips.infrastructure.vinfast_locator_client import (
    VinFastBulkDataset,
    VinFastLocatorClient,
)


@dataclass(frozen=True)
class StationIngestionResult:
    provider: str
    generation: str
    status: str
    location_count: int


@dataclass(frozen=True)
class StationHydrationResult:
    attempted: int
    verified: int
    partial: int
    failed: int


class StationIngestionService:
    PROVIDER = "VINFAST_OFFICIAL"

    def __init__(
        self,
        *,
        repository: StationCatalogRepository,
        client: VinFastLocatorClient,
        dataset_refresh_seconds: float,
    ):
        self._repository = repository
        self._client = client
        self._dataset_refresh_seconds = max(1.0, dataset_refresh_seconds)

    def sync(self) -> StationIngestionResult:
        metadata = self._client.fetch_metadata()
        active = self._repository.get_active_dataset_version(self.PROVIDER)
        if active is not None and active.generation == metadata.generation:
            return StationIngestionResult(
                provider=self.PROVIDER,
                generation=metadata.generation,
                status="NOOP",
                location_count=0,
            )

        dataset = self._client.fetch_bulk_dataset(metadata)
        locations = _normalize_bulk_locations(dataset)
        if not locations:
            raise StationProviderError(
                "VinFast bulk dataset contains no public car charging locations.",
                code="PROVIDER_INVALID_SCHEMA",
            )
        version = StationDatasetVersion(
            id=str(uuid4()),
            provider=self.PROVIDER,
            generation=dataset.generation,
            source_url=dataset.source_url,
            source_last_modified_at=dataset.source_last_modified_at,
            retrieved_at=dataset.retrieved_at,
            valid_until=dataset.retrieved_at + timedelta(seconds=self._dataset_refresh_seconds),
            checksum=dataset.checksum,
            status="ACTIVE",
            metadata=metadata.raw_payload,
        )
        count = self._repository.ingest_dataset(version, locations)
        return StationIngestionResult(
            provider=self.PROVIDER,
            generation=dataset.generation,
            status="INGESTED",
            location_count=count,
        )


class StationDetailHydrator:
    PROVIDER = "VINFAST_OFFICIAL"

    def __init__(
        self,
        *,
        repository: StationCatalogRepository,
        client: VinFastLocatorClient,
        detail_max_stale_seconds: float,
    ):
        self._repository = repository
        self._client = client
        self._detail_max_stale_seconds = max(1.0, detail_max_stale_seconds)

    def hydrate(self, *, limit: int = 100) -> StationHydrationResult:
        self._repository.downgrade_stale_details(
            provider=self.PROVIDER,
            cutoff=datetime.now(UTC)
            - timedelta(seconds=self._detail_max_stale_seconds),
        )
        locations = self._repository.list_locations_for_hydration(
            provider=self.PROVIDER,
            limit=limit,
        )
        verified = 0
        partial = 0
        failed = 0
        attempted = 0
        for location in locations:
            attempted += 1
            try:
                detail, retrieved_at = self._client.fetch_detail(
                    location.external_id,
                    location.dataset_generation,
                )
                evses, source_updated_at, quality = self._normalize_detail(
                    detail,
                    retrieved_at,
                )
                self._repository.upsert_location_detail(
                    provider=self.PROVIDER,
                    external_id=location.external_id,
                    evses=evses,
                    detail_quality=quality,
                    source_url=f"{self._client.detail_base_url}/{location.external_id}",
                    source_updated_at=source_updated_at,
                    retrieved_at=retrieved_at,
                    raw_detail=detail,
                )
                if quality == "VERIFIED":
                    verified += 1
                else:
                    partial += 1
            except StationProviderError as exc:
                failed += 1
                if exc.code in {"PROVIDER_ACCESS_DENIED", "PROVIDER_RATE_LIMITED"}:
                    break
        return StationHydrationResult(
            attempted=attempted,
            verified=verified,
            partial=partial,
            failed=failed,
        )

    def _normalize_detail(
        self,
        detail: dict,
        retrieved_at: datetime,
    ) -> tuple[tuple[StationEvseData, ...], datetime | None, str]:
        nested = detail.get("data")
        if not isinstance(nested, dict):
            return (), None, "PARTIAL"
        station_status = str(detail.get("charging_status", "")).upper()
        depot_status = str((nested.get("extra_data") or {}).get("depot_status", "")).upper()
        source_updated_at = _parse_iso_datetime(nested.get("last_updated"))
        evse_results: list[StationEvseData] = []
        for evse in nested.get("evses") or []:
            if not isinstance(evse, dict):
                continue
            connectors: list[StationConnectorData] = []
            connector_timestamps: list[datetime] = []
            for connector in evse.get("connectors") or []:
                if not isinstance(connector, dict):
                    continue
                raw_standard = str(connector.get("standard", ""))
                normalized = _normalize_connector(raw_standard)
                try:
                    power_kw = float(connector["max_electric_power"]) / 1000.0
                except (KeyError, TypeError, ValueError):
                    continue
                if not normalized or power_kw <= 0:
                    continue
                connector_updated_at = _parse_iso_datetime(connector.get("last_updated"))
                if connector_updated_at is not None:
                    connector_timestamps.append(connector_updated_at)
                connectors.append(
                    StationConnectorData(
                        connector_type=raw_standard,
                        normalized_connector=normalized,
                        max_electric_power_kw=power_kw,
                        raw_payload=connector,
                    )
                )
            evse_results.append(
                StationEvseData(
                    external_evse_id=str(evse.get("id")) if evse.get("id") is not None else None,
                    depot_status=str(evse.get("depot_status") or depot_status or "") or None,
                    status=str(evse.get("status") or station_status or "") or None,
                    retrieved_at=retrieved_at,
                    source_updated_at=max(connector_timestamps, default=source_updated_at),
                    raw_payload=evse,
                    connectors=tuple(connectors),
                )
            )

        usable_connectors = [connector for evse in evse_results for connector in evse.connectors]
        age_seconds = (
            (retrieved_at - source_updated_at).total_seconds() if source_updated_at is not None else float("inf")
        )
        status_usable = station_status in {"ACTIVE", "BUSY"} and depot_status not in {
            "MAINTAINING",
            "INACTIVE",
            "UNAVAILABLE",
            "OUTOFORDER",
            "BLOCKED",
        }
        quality = (
            "VERIFIED"
            if status_usable and usable_connectors and age_seconds <= self._detail_max_stale_seconds
            else "PARTIAL"
        )
        return tuple(evse_results), source_updated_at, quality


def _normalize_bulk_locations(dataset: VinFastBulkDataset) -> list[StationLocationUpsert]:
    locations: list[StationLocationUpsert] = []
    for record in dataset.records:
        if record.get("category_slug") != "car_charging_station":
            continue
        if record.get("charging_publish") is not True:
            continue
        if str(record.get("access_type", "")).lower() != "public":
            continue
        try:
            external_id = str(record["entity_id"])
            name = str(record["name"])
            latitude = float(record["lat"])
            longitude = float(record["lng"])
        except (KeyError, TypeError, ValueError):
            continue
        locations.append(
            StationLocationUpsert(
                external_id=external_id,
                name=name,
                address=str(record.get("address", "")),
                category_slug=str(record.get("category_slug") or "") or None,
                access_type=str(record.get("access_type") or "") or None,
                charging_publish=True,
                station_status=str(record.get("charging_status") or "").upper() or None,
                latitude=latitude,
                longitude=longitude,
                source_url=dataset.source_url,
                source_updated_at=dataset.source_last_modified_at,
                retrieved_at=dataset.retrieved_at,
                raw_payload=record,
                detail_quality="PARTIAL",
            )
        )
    return locations
