from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from src.packages.core.trips.application.station_graph_builder import StationGraphBuilder
from src.packages.core.trips.domain.station_catalog import (
    StationDatasetVersion,
    StationLocationUpsert,
)
from src.packages.core.trips.infrastructure.models import ChargingLocationModel
from src.packages.core.trips.infrastructure.osrm_routing import RoadMatrixCell
from src.packages.core.trips.infrastructure.routing import (
    InMemoryRoutingProvider,
    RoutingUnavailableError,
)
from src.packages.core.trips.infrastructure.station_catalog_repository import (
    SqlAlchemyStationCatalogRepository,
)
from src.packages.core.trips.infrastructure.station_graph_repository import (
    SqlAlchemyStationEdgeRepository,
    edge_from_route,
)


def _repositories(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'graph.db'}"
    catalog = SqlAlchemyStationCatalogRepository(database_url)
    catalog.ensure_schema()
    now = datetime.now(UTC)
    catalog.ingest_dataset(
        StationDatasetVersion(
            id="dataset-1",
            provider="VINFAST_OFFICIAL",
            generation="generation-1",
            source_url="https://example.test/dataset",
            source_last_modified_at=now,
            retrieved_at=now,
            valid_until=None,
            checksum="checksum",
            status="ACTIVE",
        ),
        [
            StationLocationUpsert(
                external_id=f"station-{index}",
                name=f"Station {index}",
                address="Test",
                category_slug="car-charging",
                access_type="Public",
                charging_publish=True,
                station_status="ACTIVE",
                latitude=10.0,
                longitude=106.0 + index,
                source_url="https://example.test/station",
                source_updated_at=now,
                retrieved_at=now,
                raw_payload={},
            )
            for index in range(3)
        ],
    )
    stations = catalog.query_locations_for_planning(
        provider="VINFAST_OFFICIAL",
        min_lat=-90,
        max_lat=90,
        min_lon=-180,
        max_lon=180,
    )
    return (
        database_url,
        catalog,
        stations,
        SqlAlchemyStationEdgeRepository(database_url, max_age_seconds=3600),
    )


def _activate_empty_graph(edges, catalog, stations, *, road_version: str) -> str:
    dataset = catalog.get_active_dataset_version("VINFAST_OFFICIAL")
    version = edges.create_or_resume_graph_version(
        routing_provider="TEST_FIXTURE",
        routing_profile="car",
        road_version=road_version,
        station_dataset_version_id=dataset.id,
        expected_node_count=len(stations),
        metadata={"test": True},
    )
    edges.checkpoint_graph_version(
        version.id,
        expected_processed_node_count=0,
        expected_previous_last_location_id=None,
        processed_node_delta=len(stations),
        last_location_id=stations[-1].location_id,
    )
    return edges.activate_graph_version(version.id).id


def test_station_edges_are_directed_and_exactly_versioned(tmp_path) -> None:
    _database_url, catalog, stations, edges = _repositories(tmp_path)
    _activate_empty_graph(edges, catalog, stations, road_version="road-v2")
    now = datetime.now(UTC)
    route = InMemoryRoutingProvider().get_route(10.0, 106.0, 10.0, 107.0)
    edge = edge_from_route(
        from_location_id=stations[0].location_id,
        to_location_id=stations[1].location_id,
        routing_provider="TEST_FIXTURE",
        routing_profile="car",
        road_version="road-v2",
        route=route,
        max_age_seconds=3600,
    )
    edges.upsert_edge(edge)

    assert edges.get_edge(
        stations[0].location_id, stations[1].location_id, "TEST_FIXTURE", "road-v2"
    ) is not None
    assert edges.get_edge(
        stations[1].location_id, stations[0].location_id, "TEST_FIXTURE", "road-v2"
    ) is None
    assert edges.get_edge(
        stations[0].location_id, stations[1].location_id, "GOONG_DIRECTIONS", "road-v2"
    ) is None
    assert edges.get_edge(
        stations[0].location_id, stations[1].location_id, "TEST_FIXTURE", "road-v1"
    ) is None

    edges.upsert_edge(
        edge.__class__(
            **{
                **edge.__dict__,
                "computed_at": now - timedelta(hours=2),
                "valid_until": now - timedelta(hours=1),
            }
        )
    )
    assert edges.get_edge(
        stations[0].location_id, stations[1].location_id, "TEST_FIXTURE", "road-v2"
    ) is None


class _Catalog:
    def __init__(self):
        self.stations = [
            SimpleNamespace(
                location_id=index,
                latitude=10.0,
                longitude=106.0 + index * 0.1,
                active=True,
                detail_quality="PARTIAL",
            )
            for index in range(1, 7)
        ]
        self.stations.extend(
            [
                SimpleNamespace(
                    location_id=7,
                    latitude=10.0,
                    longitude=106.7,
                    active=True,
                    detail_quality="UNVERIFIED",
                ),
                SimpleNamespace(
                    location_id=8,
                    latitude=10.0,
                    longitude=106.8,
                    active=False,
                    detail_quality="PARTIAL",
                ),
            ]
        )

    def get_active_dataset_version(self, _provider):
        return SimpleNamespace(id="dataset-1", generation="generation-1")

    def query_locations_for_planning(self, *, min_lat, max_lat, min_lon, max_lon, **_kwargs):
        return [
            station
            for station in self.stations
            if min_lat <= station.latitude <= max_lat
            and min_lon <= station.longitude <= max_lon
        ]


class _Edges:
    def __init__(self):
        self.values = {}

    def get_edge(self, from_id, to_id, routing_provider, road_version):
        return self.values.get((from_id, to_id, routing_provider, road_version))

    def upsert_edge(self, edge):
        self.values[
            (
                edge.from_location_id,
                edge.to_location_id,
                edge.routing_provider,
                edge.road_version,
            )
        ] = edge

    def neighbors(self, location_id, routing_provider, road_version):
        return []


class _MatrixRoutingProvider:
    def __init__(self):
        self.calls = 0

    def get_route_matrix(self, _origin_lat, _origin_lng, destinations):
        self.calls += 1
        now = datetime.now(UTC)
        return tuple(
            RoadMatrixCell(
                distance_km=float(index + 1),
                duration_minutes=float(index + 2),
                provider="OSRM",
                source_url="http://osrm.test/table/v1/driving",
                retrieved_at=now,
            )
            for index, _destination in enumerate(destinations)
        )

    def get_route(self, *_args, **_kwargs):
        raise AssertionError("Matrix graph build must not call route per edge.")


class _UnavailableMatrixRoutingProvider:
    def get_route_matrix(self, *_args, **_kwargs):
        raise RoutingUnavailableError("OSRM is unavailable")

    def get_route(self, *_args, **_kwargs):
        raise AssertionError("Matrix graph build must not fall back to route calls.")


def test_graph_builder_is_sparse_directed_and_reuses_current_edges() -> None:
    catalog = _Catalog()
    edges = _Edges()
    builder = StationGraphBuilder(
        catalog_repository=catalog,
        edge_repository=edges,
        routing_provider=InMemoryRoutingProvider(),
        provider="VINFAST_OFFICIAL",
        routing_provider_name="TEST_FIXTURE",
        routing_profile="car",
        road_version="fixture-road-v1",
        max_neighbors=2,
        coarse_radius_km=100,
        max_road_leg_km=150,
        edge_max_age_seconds=3600,
    )
    first = builder.build()
    assert first.considered_locations == 6
    assert first.edges_written == first.candidate_pairs
    assert first.candidate_pairs <= len(catalog.stations) * 2
    assert first.candidate_pairs < len(catalog.stations) * (len(catalog.stations) - 1)
    assert any(
        reverse not in edges.values
        for origin, destination, provider, version in edges.values.keys()
        for reverse in [(destination, origin, provider, version)]
    )

    second = builder.build()
    assert second.edges_written == 0
    assert second.cache_hits == first.candidate_pairs


def test_edge_repository_caps_current_out_degree_and_hides_inactive_nodes(tmp_path) -> None:
    database_url, catalog, stations, _uncapped = _repositories(tmp_path)
    edges = SqlAlchemyStationEdgeRepository(
        database_url,
        max_age_seconds=3600,
        max_outgoing_neighbors=1,
    )
    _activate_empty_graph(edges, catalog, stations, road_version="road-v1")
    provider = InMemoryRoutingProvider()
    for destination in (stations[2], stations[1]):
        route = provider.get_route(
            stations[0].latitude,
            stations[0].longitude,
            destination.latitude,
            destination.longitude,
        )
        edges.upsert_edge(
            edge_from_route(
                from_location_id=stations[0].location_id,
                to_location_id=destination.location_id,
                routing_provider="TEST_FIXTURE",
                routing_profile="car",
                road_version="road-v1",
                route=route,
                max_age_seconds=3600,
            )
        )

    neighbors = edges.neighbors(
        stations[0].location_id,
        "TEST_FIXTURE",
        "road-v1",
    )
    assert [edge.to_location_id for edge in neighbors] == [stations[1].location_id]

    with edges._session_factory() as session:
        destination = session.get(ChargingLocationModel, stations[1].location_id)
        destination.active = False
        session.commit()

    assert (
        edges.get_edge(
            stations[0].location_id,
            stations[1].location_id,
            "TEST_FIXTURE",
            "road-v1",
        )
        is None
    )
    assert edges.neighbors(stations[0].location_id, "TEST_FIXTURE", "road-v1") == []


def test_matrix_graph_build_is_resumable_and_activates_atomically(tmp_path) -> None:
    _database_url, catalog, stations, edges = _repositories(tmp_path)
    matrix = _MatrixRoutingProvider()
    builder = StationGraphBuilder(
        catalog_repository=catalog,
        edge_repository=edges,
        routing_provider=matrix,
        provider="VINFAST_OFFICIAL",
        routing_provider_name="OSRM",
        routing_profile="driving",
        road_version="osrm-test-v1",
        max_neighbors=2,
        coarse_radius_km=500,
        max_road_leg_km=500,
        edge_max_age_seconds=3600,
    )

    first = builder.build(origin_limit=1)

    assert first.graph_version_status == "BUILDING"
    assert first.processed_node_count == 1
    assert first.expected_node_count == 3
    assert first.matrix_calls == 1
    assert first.route_calls == 0
    assert (
        edges.get_edge(
            stations[0].location_id,
            stations[1].location_id,
            "OSRM",
            "osrm-test-v1",
        )
        is None
    )

    second = builder.build(origin_limit=2, graph_version_id=first.graph_version_id)

    assert second.graph_version_id == first.graph_version_id
    assert second.graph_version_status == "ACTIVE"
    assert second.processed_node_count == 3
    assert second.matrix_calls == 2
    assert (
        edges.get_edge(
            stations[0].location_id,
            stations[1].location_id,
            "OSRM",
            "osrm-test-v1",
        )
        is not None
    )
    assert sum(
        len(edges.neighbors(station.location_id, "OSRM", "osrm-test-v1"))
        for station in stations
    ) <= len(stations) * 2

    noop = builder.build()
    assert noop.graph_version_status == "ACTIVE"
    assert noop.matrix_calls == 0


def test_graph_checkpoint_rejects_a_stale_worker(tmp_path) -> None:
    _database_url, catalog, stations, edges = _repositories(tmp_path)
    dataset = catalog.get_active_dataset_version("VINFAST_OFFICIAL")
    version = edges.create_or_resume_graph_version(
        routing_provider="OSRM",
        routing_profile="driving",
        road_version="osrm-stale-checkpoint-v1",
        station_dataset_version_id=dataset.id,
        expected_node_count=len(stations),
        metadata={"test": True},
    )
    edges.checkpoint_graph_version(
        version.id,
        expected_processed_node_count=0,
        expected_previous_last_location_id=None,
        processed_node_delta=1,
        last_location_id=stations[0].location_id,
    )

    with pytest.raises(ValueError, match="stale"):
        edges.checkpoint_graph_version(
            version.id,
            expected_processed_node_count=0,
            expected_previous_last_location_id=None,
            processed_node_delta=1,
            last_location_id=stations[0].location_id,
        )


def test_matrix_failure_does_not_advance_or_activate_graph_version(tmp_path) -> None:
    _database_url, catalog, stations, edges = _repositories(tmp_path)
    builder = StationGraphBuilder(
        catalog_repository=catalog,
        edge_repository=edges,
        routing_provider=_UnavailableMatrixRoutingProvider(),
        provider="VINFAST_OFFICIAL",
        routing_provider_name="OSRM",
        routing_profile="driving",
        road_version="osrm-unavailable-v1",
        max_neighbors=2,
        coarse_radius_km=500,
        max_road_leg_km=500,
        edge_max_age_seconds=3600,
    )

    with pytest.raises(RoutingUnavailableError, match="unavailable"):
        builder.build(origin_limit=1)

    dataset = catalog.get_active_dataset_version("VINFAST_OFFICIAL")
    version = edges.create_or_resume_graph_version(
        routing_provider="OSRM",
        routing_profile="driving",
        road_version="osrm-unavailable-v1",
        station_dataset_version_id=dataset.id,
        expected_node_count=len(stations),
        metadata={"test": True},
    )
    assert version.status == "BUILDING"
    assert version.processed_node_count == 0
    assert version.last_location_id is None
    assert version.edge_count == 0
