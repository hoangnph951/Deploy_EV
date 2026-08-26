from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from src.packages.core.trips.application.station_catalog_repository import (
    StationCatalogRepository,
)
from src.packages.core.trips.application.station_edge_repository import (
    StationEdgeRepository,
)
from src.packages.core.trips.domain.station_catalog import CatalogStation
from src.packages.core.trips.domain.station_graph import StationEdge, StationGraphVersion
from src.packages.core.trips.infrastructure.routing import (
    RoutingProvider,
    RoutingProviderError,
    haversine_distance_km,
)
from src.packages.core.trips.infrastructure.station_graph_repository import (
    edge_from_road_facts,
    edge_from_route,
)


class RoadMatrixCell(Protocol):
    distance_km: float
    duration_minutes: float
    provider: str
    source_url: str
    retrieved_at: datetime


@dataclass(frozen=True)
class GraphBuildResult:
    considered_locations: int
    candidate_pairs: int
    cache_hits: int
    edges_written: int
    route_failures: int
    road_distance_rejections: int
    last_location_id: int | None
    matrix_calls: int
    route_calls: int
    graph_version_id: str | None
    graph_version_status: str | None
    expected_node_count: int
    processed_node_count: int


class StationGraphBuilder:
    """Build only directed K-nearest road edges; never an all-pairs graph."""

    def __init__(
        self,
        *,
        catalog_repository: StationCatalogRepository,
        edge_repository: StationEdgeRepository,
        routing_provider: RoutingProvider,
        provider: str,
        routing_provider_name: str,
        routing_profile: str,
        road_version: str,
        max_neighbors: int,
        coarse_radius_km: float,
        max_road_leg_km: float,
        edge_max_age_seconds: float,
    ):
        self._catalog_repository = catalog_repository
        self._edge_repository = edge_repository
        self._routing_provider = routing_provider
        self._provider = provider
        self._routing_provider_name = routing_provider_name
        self._routing_profile = routing_profile
        self._road_version = road_version
        self._max_neighbors = max(1, max_neighbors)
        self._coarse_radius_km = max(1.0, coarse_radius_km)
        self._max_road_leg_km = max(1.0, max_road_leg_km)
        self._edge_max_age_seconds = max(0.0, edge_max_age_seconds)

    def build(
        self,
        *,
        origin_limit: int | None = None,
        start_after_location_id: int | None = None,
        graph_version_id: str | None = None,
    ) -> GraphBuildResult:
        dataset = self._catalog_repository.get_active_dataset_version(self._provider)
        if dataset is None:
            raise ValueError("An active station dataset is required for graph building.")
        count_query = getattr(self._catalog_repository, "count_graph_locations", None)
        if callable(count_query):
            expected_node_count = count_query(
                provider=self._provider,
                dataset_version_id=dataset.id,
            )
        else:
            expected_node_count = len(
                self._catalog_repository.query_locations_for_planning(
                    provider=self._provider,
                    min_lat=-90.0,
                    max_lat=90.0,
                    min_lon=-180.0,
                    max_lon=180.0,
                )
            )

        graph_version = self._prepare_graph_version(
            graph_version_id=graph_version_id,
            station_dataset_version_id=dataset.id,
            station_dataset_generation=dataset.generation,
            expected_node_count=expected_node_count,
        )
        if graph_version is not None and graph_version.status == "ACTIVE":
            return _empty_result(graph_version, expected_node_count)
        if graph_version is not None:
            start_after_location_id = graph_version.last_location_id

        graph_query = getattr(self._catalog_repository, "query_graph_locations", None)
        if callable(graph_query):
            locations = graph_query(
                provider=self._provider,
                dataset_version_id=dataset.id,
                start_after_location_id=start_after_location_id,
                limit=origin_limit,
            )
        else:
            locations = self._catalog_repository.query_locations_for_planning(
                provider=self._provider,
                min_lat=-90.0,
                max_lat=90.0,
                min_lon=-180.0,
                max_lon=180.0,
            )
        locations = [
            location
            for location in locations
            if _eligible_graph_location(location)
            and (
                start_after_location_id is None
                or location.location_id > start_after_location_id
            )
        ]
        if origin_limit is not None:
            locations = locations[: max(0, origin_limit)]
        cache_hits = 0
        candidate_pairs = 0
        edges_written = 0
        route_failures = 0
        road_distance_rejections = 0
        matrix_calls = 0
        route_calls = 0
        pending_edges: list[StationEdge] = []
        batch_edge_query = getattr(self._edge_repository, "get_build_edges_batch", None)
        existing_by_origin = (
            batch_edge_query(
                graph_version.id,
                [location.location_id for location in locations],
            )
            if callable(batch_edge_query) and graph_version is not None and locations
            else {}
        )
        batch_spatial_query = getattr(
            self._catalog_repository, "query_nearby_graph_locations_batch", None
        )
        batch_destinations = (
            batch_spatial_query(
                provider=self._provider,
                dataset_version_id=dataset.id,
                origin_ids=[location.location_id for location in locations],
                radius_km=self._coarse_radius_km,
                limit=self._max_neighbors + 1,
            )
            if callable(batch_spatial_query) and locations
            else {}
        )
        for origin in locations:
            destinations = (
                [
                    station
                    for station in batch_destinations.get(origin.location_id, [])
                    if station.location_id != origin.location_id
                    and _eligible_graph_location(station)
                ][: self._max_neighbors]
                if callable(batch_spatial_query)
                else self._coarse_neighbors(origin, dataset.id)
            )
            candidate_pairs += len(destinations)
            existing = (
                existing_by_origin.get(origin.location_id, {})
                if callable(batch_edge_query) and graph_version is not None
                else self._existing_build_edges(
                    graph_version_id=graph_version.id if graph_version is not None else None,
                    origin=origin,
                    destinations=destinations,
                )
            )
            cache_hits += len(existing)
            pending = [
                destination
                for destination in destinations
                if destination.location_id not in existing
            ]
            if not pending:
                continue
            matrix_method = getattr(self._routing_provider, "get_route_matrix", None)
            if callable(matrix_method) and graph_version is not None:
                matrix_calls += 1
                try:
                    cells = matrix_method(
                        origin.latitude,
                        origin.longitude,
                        [
                            (destination.latitude, destination.longitude)
                            for destination in pending
                        ],
                    )
                except RoutingProviderError:
                    # A failed local matrix request is an operational failure, not
                    # proof that every candidate pair is unroutable. Do not advance
                    # the atomic graph checkpoint.
                    raise
                edges = []
                for destination, cell in zip(pending, cells, strict=True):
                    if cell is None:
                        route_failures += 1
                        continue
                    if cell.provider != self._routing_provider_name:
                        route_failures += 1
                        continue
                    if cell.distance_km <= 0 or cell.distance_km > self._max_road_leg_km:
                        road_distance_rejections += 1
                        continue
                    edges.append(
                        edge_from_road_facts(
                            graph_version_id=graph_version.id,
                            from_location_id=origin.location_id,
                            to_location_id=destination.location_id,
                            routing_provider=self._routing_provider_name,
                            routing_profile=self._routing_profile,
                            road_version=self._road_version,
                            distance_km=cell.distance_km,
                            duration_minutes=cell.duration_minutes,
                            provider_source_url=cell.source_url,
                            provider_retrieved_at=cell.retrieved_at,
                        )
                    )
                pending_edges.extend(edges)
                edges_written += len(edges)
                continue

            for destination in pending:
                route_calls += 1
                try:
                    route = self._routing_provider.get_route(
                        origin.latitude,
                        origin.longitude,
                        destination.latitude,
                        destination.longitude,
                    )
                except RoutingProviderError:
                    route_failures += 1
                    continue
                if route.provider != self._routing_provider_name:
                    route_failures += 1
                    continue
                if route.distance_km > self._max_road_leg_km:
                    road_distance_rejections += 1
                    continue
                pending_edges.append(
                    edge_from_route(
                        from_location_id=origin.location_id,
                        to_location_id=destination.location_id,
                        routing_provider=self._routing_provider_name,
                        routing_profile=self._routing_profile,
                        road_version=self._road_version,
                        route=route,
                        max_age_seconds=self._edge_max_age_seconds,
                        graph_version_id=(
                            graph_version.id if graph_version is not None else None
                        ),
                    )
                )
                edges_written += 1
        batch_edge_writer = getattr(self._edge_repository, "upsert_edge_batches", None)
        if pending_edges:
            if callable(batch_edge_writer):
                batch_edge_writer(pending_edges)
            else:
                for edge in pending_edges:
                    self._edge_repository.upsert_edge(edge)
        if graph_version is not None:
            graph_version = self._edge_repository.checkpoint_graph_version(
                graph_version.id,
                expected_processed_node_count=graph_version.processed_node_count,
                expected_previous_last_location_id=graph_version.last_location_id,
                processed_node_delta=len(locations),
                last_location_id=locations[-1].location_id if locations else None,
            )
            if graph_version.processed_node_count == graph_version.expected_node_count:
                graph_version = self._edge_repository.activate_graph_version(
                    graph_version.id
                )
        return GraphBuildResult(
            considered_locations=len(locations),
            candidate_pairs=candidate_pairs,
            cache_hits=cache_hits,
            edges_written=edges_written,
            route_failures=route_failures,
            road_distance_rejections=road_distance_rejections,
            last_location_id=locations[-1].location_id if locations else None,
            matrix_calls=matrix_calls,
            route_calls=route_calls,
            graph_version_id=graph_version.id if graph_version is not None else None,
            graph_version_status=(
                graph_version.status if graph_version is not None else None
            ),
            expected_node_count=expected_node_count,
            processed_node_count=(
                graph_version.processed_node_count
                if graph_version is not None
                else len(locations)
            ),
        )

    def _prepare_graph_version(
        self,
        *,
        graph_version_id: str | None,
        station_dataset_version_id: str,
        station_dataset_generation: str | None,
        expected_node_count: int,
    ) -> StationGraphVersion | None:
        get_version = getattr(self._edge_repository, "get_graph_version", None)
        create_version = getattr(
            self._edge_repository, "create_or_resume_graph_version", None
        )
        if not callable(get_version) or not callable(create_version):
            return None
        if graph_version_id is not None:
            version = get_version(graph_version_id)
            if version is None:
                raise ValueError("Requested graph version does not exist.")
            if (
                version.routing_provider != self._routing_provider_name
                or version.routing_profile != self._routing_profile
                or version.road_version != self._road_version
                or version.station_dataset_version_id != station_dataset_version_id
            ):
                raise ValueError("Requested graph version does not match this build.")
            if version.status not in {"BUILDING", "ACTIVE"}:
                raise ValueError("Requested graph version cannot be resumed.")
            return version
        return create_version(
            routing_provider=self._routing_provider_name,
            routing_profile=self._routing_profile,
            road_version=self._road_version,
            station_dataset_version_id=station_dataset_version_id,
            expected_node_count=expected_node_count,
            metadata={
                "station_dataset_generation": station_dataset_generation,
                "max_neighbors": self._max_neighbors,
                "coarse_radius_km": self._coarse_radius_km,
                "max_road_leg_km": self._max_road_leg_km,
            },
        )

    def _existing_build_edges(
        self,
        *,
        graph_version_id: str | None,
        origin: CatalogStation,
        destinations: list[CatalogStation],
    ) -> dict[int, object]:
        get_build_edges = getattr(self._edge_repository, "get_build_edges", None)
        if graph_version_id is not None and callable(get_build_edges):
            return get_build_edges(
                graph_version_id,
                origin.location_id,
                [destination.location_id for destination in destinations],
            )
        return {
            destination.location_id: edge
            for destination in destinations
            if (
                edge := self._edge_repository.get_edge(
                    origin.location_id,
                    destination.location_id,
                    self._routing_provider_name,
                    self._road_version,
                )
            )
            is not None
        }

    def _coarse_neighbors(
        self,
        origin: CatalogStation,
        dataset_version_id: str,
    ) -> list[CatalogStation]:
        graph_spatial_query = getattr(
            self._catalog_repository, "query_nearby_graph_locations", None
        )
        if callable(graph_spatial_query):
            nearby = graph_spatial_query(
                provider=self._provider,
                dataset_version_id=dataset_version_id,
                latitude=origin.latitude,
                longitude=origin.longitude,
                radius_km=self._coarse_radius_km,
                limit=self._max_neighbors + 1,
            )
            return [
                station
                for station in nearby
                if station.location_id != origin.location_id
                and _eligible_graph_location(station)
            ][: self._max_neighbors]
        spatial_query = getattr(
            self._catalog_repository, "query_nearby_locations", None
        )
        if callable(spatial_query):
            nearby = spatial_query(
                provider=self._provider,
                latitude=origin.latitude,
                longitude=origin.longitude,
                radius_km=self._coarse_radius_km,
                limit=self._max_neighbors + 1,
            )
            return [
                station
                for station in nearby
                if station.location_id != origin.location_id
                and _eligible_graph_location(station)
            ][: self._max_neighbors]
        lat_delta = self._coarse_radius_km / 111.0
        lon_scale = max(0.1, math.cos(math.radians(origin.latitude)))
        lon_delta = self._coarse_radius_km / (111.0 * lon_scale)
        nearby = self._catalog_repository.query_locations_for_planning(
            provider=self._provider,
            min_lat=max(-90.0, origin.latitude - lat_delta),
            max_lat=min(90.0, origin.latitude + lat_delta),
            min_lon=max(-180.0, origin.longitude - lon_delta),
            max_lon=min(180.0, origin.longitude + lon_delta),
        )
        ranked = sorted(
            (
                (
                    haversine_distance_km(
                        origin.latitude,
                        origin.longitude,
                        candidate.latitude,
                        candidate.longitude,
                    ),
                    candidate,
                )
                for candidate in nearby
                if candidate.location_id != origin.location_id
                and _eligible_graph_location(candidate)
            ),
            key=lambda item: (item[0], item[1].location_id),
        )
        return [
            candidate
            for distance, candidate in ranked
            if distance <= self._coarse_radius_km
        ][: self._max_neighbors]


def _eligible_graph_location(location: CatalogStation) -> bool:
    return (
        location.active
        and location.detail_quality in {"VERIFIED", "PARTIAL"}
        and math.isfinite(location.latitude)
        and math.isfinite(location.longitude)
        and -90.0 <= location.latitude <= 90.0
        and -180.0 <= location.longitude <= 180.0
    )


def _empty_result(
    graph_version: StationGraphVersion,
    expected_node_count: int,
) -> GraphBuildResult:
    return GraphBuildResult(
        considered_locations=0,
        candidate_pairs=0,
        cache_hits=0,
        edges_written=0,
        route_failures=0,
        road_distance_rejections=0,
        last_location_id=graph_version.last_location_id,
        matrix_calls=0,
        route_calls=0,
        graph_version_id=graph_version.id,
        graph_version_status=graph_version.status,
        expected_node_count=expected_node_count,
        processed_node_count=graph_version.processed_node_count,
    )
