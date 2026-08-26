from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

StationDetailQuality = Literal["VERIFIED", "PARTIAL", "UNVERIFIED"]
DatasetStatus = Literal["ACTIVE", "SUPERSEDED", "FAILED"]


@dataclass(frozen=True)
class StationDatasetVersion:
    id: str
    provider: str
    generation: str | None
    source_url: str
    source_last_modified_at: datetime | None
    retrieved_at: datetime
    valid_until: datetime | None
    checksum: str | None
    status: DatasetStatus
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class StationLocationUpsert:
    external_id: str
    name: str
    address: str
    category_slug: str | None
    access_type: str | None
    charging_publish: bool
    station_status: str | None
    latitude: float
    longitude: float
    source_url: str | None
    source_updated_at: datetime | None
    retrieved_at: datetime
    raw_payload: dict
    detail_quality: StationDetailQuality = "PARTIAL"


@dataclass(frozen=True)
class StationConnectorData:
    connector_type: str
    normalized_connector: str
    max_electric_power_kw: float
    raw_payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class StationEvseData:
    external_evse_id: str | None
    depot_status: str | None
    status: str | None
    retrieved_at: datetime
    source_updated_at: datetime | None
    raw_payload: dict
    connectors: tuple[StationConnectorData, ...]


@dataclass(frozen=True)
class CatalogStation:
    location_id: int
    provider: str
    external_id: str
    dataset_version_id: str
    dataset_generation: str | None
    dataset_retrieved_at: datetime
    dataset_source_updated_at: datetime | None
    name: str
    address: str
    access_type: str | None
    station_status: str | None
    latitude: float
    longitude: float
    source_url: str | None
    source_updated_at: datetime | None
    retrieved_at: datetime
    active: bool
    detail_quality: StationDetailQuality
    raw_payload: dict
    evses: tuple[StationEvseData, ...]


@dataclass(frozen=True)
class StationEvidence:
    provider: str
    field_name: str
    field_value: dict
    source_url: str
    retrieved_at: datetime
    verification_status: Literal["UNVERIFIED", "CORROBORATED", "REJECTED"]
    source_updated_at: datetime | None = None
    raw_evidence: dict | None = None
    location_id: int | None = None
