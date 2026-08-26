from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.packages.core.trips.domain.station_catalog import (
    CatalogStation,
    StationDatasetVersion,
    StationEvidence,
    StationEvseData,
    StationLocationUpsert,
)


class StationCatalogRepository(Protocol):
    def get_active_dataset_version(self, provider: str) -> StationDatasetVersion | None: ...

    def ingest_dataset(
        self,
        version: StationDatasetVersion,
        locations: list[StationLocationUpsert],
    ) -> int: ...

    def query_locations_for_planning(
        self,
        *,
        provider: str,
        min_lat: float,
        max_lat: float,
        min_lon: float,
        max_lon: float,
    ) -> list[CatalogStation]: ...

    def get_location_detail(self, provider: str, external_id: str) -> CatalogStation | None: ...

    def query_nearby_locations(
        self,
        *,
        provider: str,
        latitude: float,
        longitude: float,
        radius_km: float,
        limit: int,
    ) -> list[CatalogStation]: ...

    def list_locations_for_hydration(
        self,
        *,
        provider: str,
        limit: int,
    ) -> list[CatalogStation]: ...

    def upsert_location_detail(
        self,
        *,
        provider: str,
        external_id: str,
        evses: tuple[StationEvseData, ...],
        detail_quality: str,
        source_url: str,
        source_updated_at,
        retrieved_at,
        raw_detail: dict,
    ) -> None: ...

    def save_external_evidence(self, evidence: StationEvidence) -> None: ...

    def downgrade_stale_details(self, *, provider: str, cutoff: datetime) -> int: ...
