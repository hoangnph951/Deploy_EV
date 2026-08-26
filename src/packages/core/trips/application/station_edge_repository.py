from __future__ import annotations

from typing import Protocol

from src.packages.core.trips.domain.station_graph import (
    StationEdge,
    StationGraphVersion,
)


class StationEdgeRepository(Protocol):
    def create_or_resume_graph_version(
        self,
        *,
        routing_provider: str,
        routing_profile: str,
        road_version: str,
        station_dataset_version_id: str,
        expected_node_count: int,
        metadata: dict,
    ) -> StationGraphVersion: ...

    def get_graph_version(self, graph_version_id: str) -> StationGraphVersion | None: ...

    def get_build_edges(
        self,
        graph_version_id: str,
        from_id: int,
        to_ids: list[int],
    ) -> dict[int, StationEdge]: ...

    def checkpoint_graph_version(
        self,
        graph_version_id: str,
        *,
        expected_processed_node_count: int,
        expected_previous_last_location_id: int | None,
        processed_node_delta: int,
        last_location_id: int | None,
    ) -> StationGraphVersion: ...

    def activate_graph_version(self, graph_version_id: str) -> StationGraphVersion: ...

    def get_edge(
        self,
        from_id: int,
        to_id: int,
        routing_provider: str,
        road_version: str,
    ) -> StationEdge | None: ...

    def upsert_edge(self, edge: StationEdge) -> None: ...

    def upsert_edges(self, edges: list[StationEdge]) -> None: ...

    def neighbors(
        self,
        location_id: int,
        routing_provider: str,
        road_version: str,
    ) -> list[StationEdge]: ...
