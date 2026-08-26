from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class StationGraphVersion:
    id: str
    routing_provider: str
    routing_profile: str
    road_version: str
    station_dataset_version_id: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    expected_node_count: int
    processed_node_count: int
    edge_count: int
    last_location_id: int | None
    metadata: dict
    failure_reason: str | None = None


@dataclass(frozen=True)
class StationEdge:
    from_location_id: int
    to_location_id: int
    routing_provider: str
    routing_profile: str
    road_version: str
    distance_km: float
    duration_minutes: float
    geometry_polyline: str | None
    provider_source_url: str | None
    provider_retrieved_at: datetime
    computed_at: datetime
    valid_until: datetime | None = None
    id: int | None = None
    graph_version_id: str | None = None
