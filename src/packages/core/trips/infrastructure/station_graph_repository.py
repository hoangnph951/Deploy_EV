from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, text
from sqlalchemy.orm import aliased

from src.packages.core.trips.application.station_edge_repository import (
    StationEdgeRepository,
)
from src.packages.core.trips.domain.station_graph import (
    StationEdge,
    StationGraphVersion,
)
from src.packages.core.trips.infrastructure.database import build_session_factory
from src.packages.core.trips.infrastructure.models import (
    ChargingDatasetVersionModel,
    ChargingLocationModel,
    StationEdgeModel,
    StationGraphVersionModel,
)
from src.packages.core.trips.infrastructure.routing import (
    RouteSegmentData,
    RoutingResult,
)


class SqlAlchemyStationEdgeRepository(StationEdgeRepository):
    def __init__(
        self,
        database_url: str,
        *,
        max_age_seconds: float,
        max_outgoing_neighbors: int | None = None,
    ):
        self._engine, self._session_factory = build_session_factory(database_url)
        self._max_age_seconds = max(0.0, max_age_seconds)
        self._max_outgoing_neighbors = (
            max(1, max_outgoing_neighbors)
            if max_outgoing_neighbors is not None
            else None
        )

    def create_or_resume_graph_version(
        self,
        *,
        routing_provider: str,
        routing_profile: str,
        road_version: str,
        station_dataset_version_id: str,
        expected_node_count: int,
        metadata: dict,
    ) -> StationGraphVersion:
        with self._session_factory() as session:
            dataset = (
                session.query(ChargingDatasetVersionModel)
                .filter(
                    ChargingDatasetVersionModel.id == station_dataset_version_id,
                    ChargingDatasetVersionModel.status == "ACTIVE",
                )
                .with_for_update()
                .one_or_none()
            )
            if dataset is None:
                raise ValueError("Station dataset is not active for graph building.")
            existing = (
                session.query(StationGraphVersionModel)
                .filter(
                    StationGraphVersionModel.routing_provider == routing_provider,
                    StationGraphVersionModel.routing_profile == routing_profile,
                    StationGraphVersionModel.road_version == road_version,
                    StationGraphVersionModel.station_dataset_version_id
                    == station_dataset_version_id,
                    StationGraphVersionModel.status.in_(("BUILDING", "ACTIVE")),
                )
                .order_by(StationGraphVersionModel.started_at.desc())
                .first()
            )
            if existing is not None:
                if existing.expected_node_count != expected_node_count:
                    raise ValueError(
                        "Existing graph version has a different eligible-node count."
                    )
                return _graph_version_record(existing)

            model = StationGraphVersionModel(
                id=str(uuid4()),
                routing_provider=routing_provider,
                routing_profile=routing_profile,
                road_version=road_version,
                station_dataset_version_id=station_dataset_version_id,
                status="BUILDING",
                started_at=datetime.now(UTC),
                completed_at=None,
                expected_node_count=expected_node_count,
                processed_node_count=0,
                edge_count=0,
                last_location_id=None,
                metadata_json=dict(metadata),
                failure_reason=None,
            )
            session.add(model)
            session.commit()
            return _graph_version_record(model)

    def get_graph_version(self, graph_version_id: str) -> StationGraphVersion | None:
        with self._session_factory() as session:
            model = session.get(StationGraphVersionModel, graph_version_id)
            return _graph_version_record(model) if model is not None else None

    def get_build_edges(
        self,
        graph_version_id: str,
        from_id: int,
        to_ids: list[int],
    ) -> dict[int, StationEdge]:
        if not to_ids:
            return {}
        with self._session_factory() as session:
            models = (
                session.query(StationEdgeModel)
                .filter(
                    StationEdgeModel.graph_version_id == graph_version_id,
                    StationEdgeModel.from_location_id == from_id,
                    StationEdgeModel.to_location_id.in_(to_ids),
                )
                .all()
            )
            return {model.to_location_id: _edge_record(model) for model in models}

    def get_build_edges_batch(
        self,
        graph_version_id: str,
        from_ids: list[int],
    ) -> dict[int, dict[int, StationEdge]]:
        if not from_ids:
            return {}
        grouped: dict[int, dict[int, StationEdge]] = {
            from_id: {} for from_id in from_ids
        }
        with self._session_factory() as session:
            models = (
                session.query(StationEdgeModel)
                .filter(
                    StationEdgeModel.graph_version_id == graph_version_id,
                    StationEdgeModel.from_location_id.in_(from_ids),
                )
                .all()
            )
            for model in models:
                grouped[model.from_location_id][model.to_location_id] = (
                    _edge_record(model)
                )
        return grouped

    def checkpoint_graph_version(
        self,
        graph_version_id: str,
        *,
        expected_processed_node_count: int,
        expected_previous_last_location_id: int | None,
        processed_node_delta: int,
        last_location_id: int | None,
    ) -> StationGraphVersion:
        with self._session_factory() as session:
            model = (
                session.query(StationGraphVersionModel)
                .filter(StationGraphVersionModel.id == graph_version_id)
                .with_for_update()
                .one()
            )
            if model.status != "BUILDING":
                return _graph_version_record(model)
            if (
                model.processed_node_count != expected_processed_node_count
                or model.last_location_id != expected_previous_last_location_id
            ):
                raise ValueError(
                    "Graph checkpoint is stale; another worker advanced this version."
                )
            if (
                model.last_location_id is not None
                and last_location_id is not None
                and last_location_id <= model.last_location_id
            ):
                raise ValueError("Graph checkpoint must advance monotonically.")
            model.processed_node_count = min(
                model.expected_node_count,
                model.processed_node_count + max(0, processed_node_delta),
            )
            model.last_location_id = last_location_id or model.last_location_id
            model.edge_count = (
                session.query(func.count(StationEdgeModel.id))
                .filter(StationEdgeModel.graph_version_id == graph_version_id)
                .scalar()
                or 0
            )
            session.commit()
            return _graph_version_record(model)

    def activate_graph_version(self, graph_version_id: str) -> StationGraphVersion:
        with self._session_factory() as session:
            model = (
                session.query(StationGraphVersionModel)
                .filter(StationGraphVersionModel.id == graph_version_id)
                .with_for_update()
                .one()
            )
            if model.status == "ACTIVE":
                return _graph_version_record(model)
            if model.status != "BUILDING":
                raise ValueError("Only a BUILDING graph version can be activated.")
            if model.processed_node_count != model.expected_node_count:
                raise ValueError("Graph version is incomplete and cannot be activated.")
            dataset_active = (
                session.query(ChargingDatasetVersionModel.id)
                .filter(
                    ChargingDatasetVersionModel.id
                    == model.station_dataset_version_id,
                    ChargingDatasetVersionModel.status == "ACTIVE",
                )
                .one_or_none()
            )
            if dataset_active is None:
                raise ValueError("Station dataset changed before graph activation.")

            max_degree = (
                session.query(func.count(StationEdgeModel.id).label("degree"))
                .filter(StationEdgeModel.graph_version_id == graph_version_id)
                .group_by(StationEdgeModel.from_location_id)
                .order_by(func.count(StationEdgeModel.id).desc())
                .limit(1)
                .scalar()
                or 0
            )
            if (
                self._max_outgoing_neighbors is not None
                and max_degree > self._max_outgoing_neighbors
            ):
                raise ValueError("Graph version violates the configured K-degree cap.")

            (
                session.query(StationGraphVersionModel)
                .filter(
                    StationGraphVersionModel.routing_provider
                    == model.routing_provider,
                    StationGraphVersionModel.routing_profile == model.routing_profile,
                    StationGraphVersionModel.status == "ACTIVE",
                    StationGraphVersionModel.id != model.id,
                )
                .update(
                    {
                        StationGraphVersionModel.status: "SUPERSEDED",
                        StationGraphVersionModel.completed_at: datetime.now(UTC),
                    },
                    synchronize_session=False,
                )
            )
            session.flush()
            model.status = "ACTIVE"
            model.completed_at = datetime.now(UTC)
            model.edge_count = (
                session.query(func.count(StationEdgeModel.id))
                .filter(StationEdgeModel.graph_version_id == graph_version_id)
                .scalar()
                or 0
            )
            session.commit()
            return _graph_version_record(model)

    def get_edge(
        self,
        from_id: int,
        to_id: int,
        routing_provider: str,
        road_version: str,
    ) -> StationEdge | None:
        with self._session_factory() as session:
            from_location = aliased(ChargingLocationModel)
            to_location = aliased(ChargingLocationModel)
            model = (
                session.query(StationEdgeModel)
                .join(
                    StationGraphVersionModel,
                    StationGraphVersionModel.id == StationEdgeModel.graph_version_id,
                )
                .join(
                    from_location,
                    from_location.id == StationEdgeModel.from_location_id,
                )
                .join(to_location, to_location.id == StationEdgeModel.to_location_id)
                .filter(
                    StationEdgeModel.from_location_id == from_id,
                    StationEdgeModel.to_location_id == to_id,
                    StationEdgeModel.routing_provider == routing_provider,
                    StationEdgeModel.road_version == road_version,
                    StationGraphVersionModel.status == "ACTIVE",
                    from_location.active.is_(True),
                    to_location.active.is_(True),
                )
                .one_or_none()
            )
            if model is None or not self._is_fresh(model):
                return None
            return _edge_record(model)

    def upsert_edge(self, edge: StationEdge) -> None:
        self.upsert_edges([edge])

    def upsert_edges(self, edges: list[StationEdge]) -> None:
        if not edges:
            return
        identities = {
            (
                edge.graph_version_id,
                edge.from_location_id,
                edge.routing_provider,
                edge.routing_profile,
                edge.road_version,
            )
            for edge in edges
        }
        if len(identities) != 1:
            raise ValueError("A graph edge batch must share one source and graph version.")
        with self._session_factory() as session:
            first = edges[0]
            graph_version_id = first.graph_version_id or self._active_graph_version_id(
                session,
                routing_provider=first.routing_provider,
                routing_profile=first.routing_profile,
                road_version=first.road_version,
            )
            session.query(ChargingLocationModel.id).filter(
                ChargingLocationModel.id == first.from_location_id
            ).with_for_update().one()
            existing = {
                model.to_location_id: model
                for model in session.query(StationEdgeModel)
                .filter(
                    StationEdgeModel.graph_version_id == graph_version_id,
                    StationEdgeModel.from_location_id == first.from_location_id,
                    StationEdgeModel.to_location_id.in_(
                        [edge.to_location_id for edge in edges]
                    )
                )
                .all()
            }
            for edge in edges:
                model = existing.get(edge.to_location_id)
                values = {
                    "routing_provider": edge.routing_provider,
                    "routing_profile": edge.routing_profile,
                    "road_version": edge.road_version,
                    "distance_km": edge.distance_km,
                    "duration_minutes": edge.duration_minutes,
                    "geometry_polyline": edge.geometry_polyline,
                    "provider_source_url": edge.provider_source_url,
                    "provider_retrieved_at": edge.provider_retrieved_at,
                    "computed_at": edge.computed_at,
                    "valid_until": edge.valid_until,
                }
                if model is None:
                    session.add(
                        StationEdgeModel(
                            graph_version_id=graph_version_id,
                            from_location_id=edge.from_location_id,
                            to_location_id=edge.to_location_id,
                            **values,
                        )
                    )
                else:
                    for field_name, value in values.items():
                        setattr(model, field_name, value)
            session.flush()
            if self._max_outgoing_neighbors is not None:
                excess = (
                    session.query(StationEdgeModel)
                    .filter(
                        StationEdgeModel.graph_version_id == graph_version_id,
                        StationEdgeModel.from_location_id == first.from_location_id,
                    )
                    .order_by(
                        StationEdgeModel.distance_km.asc(),
                        StationEdgeModel.to_location_id.asc(),
                    )
                    .offset(self._max_outgoing_neighbors)
                    .all()
                )
                for stale in excess:
                    session.delete(stale)
            session.commit()

    def upsert_edge_batches(self, edges: list[StationEdge]) -> None:
        if not edges:
            return
        identities = {
            (
                edge.graph_version_id,
                edge.routing_provider,
                edge.routing_profile,
                edge.road_version,
            )
            for edge in edges
        }
        if len(identities) != 1:
            raise ValueError("A graph edge batch must share one graph version.")
        with self._session_factory() as session:
            first = edges[0]
            graph_version_id = first.graph_version_id or self._active_graph_version_id(
                session,
                routing_provider=first.routing_provider,
                routing_profile=first.routing_profile,
                road_version=first.road_version,
            )
            source_ids = sorted({edge.from_location_id for edge in edges})
            (
                session.query(ChargingLocationModel.id)
                .filter(ChargingLocationModel.id.in_(source_ids))
                .order_by(ChargingLocationModel.id)
                .with_for_update()
                .all()
            )
            existing = {
                (model.from_location_id, model.to_location_id): model
                for model in session.query(StationEdgeModel)
                .filter(
                    StationEdgeModel.graph_version_id == graph_version_id,
                    StationEdgeModel.from_location_id.in_(source_ids),
                )
                .all()
            }
            for edge in edges:
                model = existing.get((edge.from_location_id, edge.to_location_id))
                values = {
                    "routing_provider": edge.routing_provider,
                    "routing_profile": edge.routing_profile,
                    "road_version": edge.road_version,
                    "distance_km": edge.distance_km,
                    "duration_minutes": edge.duration_minutes,
                    "geometry_polyline": edge.geometry_polyline,
                    "provider_source_url": edge.provider_source_url,
                    "provider_retrieved_at": edge.provider_retrieved_at,
                    "computed_at": edge.computed_at,
                    "valid_until": edge.valid_until,
                }
                if model is None:
                    session.add(
                        StationEdgeModel(
                            graph_version_id=graph_version_id,
                            from_location_id=edge.from_location_id,
                            to_location_id=edge.to_location_id,
                            **values,
                        )
                    )
                else:
                    for field_name, value in values.items():
                        setattr(model, field_name, value)
            session.flush()
            if self._max_outgoing_neighbors is not None:
                if self._engine.dialect.name == "postgresql":
                    session.execute(
                        text(
                            """
                            DELETE FROM station_edges
                            WHERE id IN (
                                SELECT id
                                FROM (
                                    SELECT
                                        id,
                                        row_number() OVER (
                                            PARTITION BY from_location_id
                                            ORDER BY distance_km, to_location_id
                                        ) AS neighbor_rank
                                    FROM station_edges
                                    WHERE graph_version_id = :graph_version_id
                                      AND from_location_id = ANY(:source_ids)
                                ) AS ranked
                                WHERE neighbor_rank > :max_neighbors
                            )
                            """
                        ),
                        {
                            "graph_version_id": graph_version_id,
                            "source_ids": source_ids,
                            "max_neighbors": self._max_outgoing_neighbors,
                        },
                    )
                else:
                    for source_id in source_ids:
                        excess = (
                            session.query(StationEdgeModel)
                            .filter(
                                StationEdgeModel.graph_version_id == graph_version_id,
                                StationEdgeModel.from_location_id == source_id,
                            )
                            .order_by(
                                StationEdgeModel.distance_km,
                                StationEdgeModel.to_location_id,
                            )
                            .offset(self._max_outgoing_neighbors)
                            .all()
                        )
                        for stale in excess:
                            session.delete(stale)
            session.commit()

    def neighbors(
        self,
        location_id: int,
        routing_provider: str,
        road_version: str,
    ) -> list[StationEdge]:
        with self._session_factory() as session:
            from_location = aliased(ChargingLocationModel)
            to_location = aliased(ChargingLocationModel)
            models = (
                session.query(StationEdgeModel)
                .join(
                    StationGraphVersionModel,
                    StationGraphVersionModel.id == StationEdgeModel.graph_version_id,
                )
                .join(
                    from_location,
                    from_location.id == StationEdgeModel.from_location_id,
                )
                .join(to_location, to_location.id == StationEdgeModel.to_location_id)
                .filter(
                    StationEdgeModel.from_location_id == location_id,
                    StationEdgeModel.routing_provider == routing_provider,
                    StationEdgeModel.road_version == road_version,
                    StationGraphVersionModel.status == "ACTIVE",
                    from_location.active.is_(True),
                    to_location.active.is_(True),
                )
                .order_by(StationEdgeModel.distance_km.asc())
                .all()
            )
            return [_edge_record(model) for model in models if self._is_fresh(model)]

    def _is_fresh(self, model: StationEdgeModel) -> bool:
        now = datetime.now(UTC)
        valid_until = _utc(model.valid_until)
        if valid_until is None:
            return True
        if valid_until <= now:
            return False
        computed_at = _utc(model.computed_at)
        return computed_at >= now - timedelta(seconds=self._max_age_seconds)

    @staticmethod
    def _active_graph_version_id(
        session,
        *,
        routing_provider: str,
        routing_profile: str,
        road_version: str,
    ) -> str:
        graph_version_id = (
            session.query(StationGraphVersionModel.id)
            .filter(
                StationGraphVersionModel.routing_provider == routing_provider,
                StationGraphVersionModel.routing_profile == routing_profile,
                StationGraphVersionModel.road_version == road_version,
                StationGraphVersionModel.status == "ACTIVE",
            )
            .scalar()
        )
        if graph_version_id is None:
            raise ValueError("No active graph version accepts runtime edge writes.")
        return graph_version_id


def edge_from_route(
    *,
    from_location_id: int,
    to_location_id: int,
    routing_provider: str,
    routing_profile: str,
    road_version: str,
    route: RoutingResult,
    max_age_seconds: float,
    graph_version_id: str | None = None,
) -> StationEdge:
    now = datetime.now(UTC)
    retrieved_at = route.retrieved_at or now
    return StationEdge(
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        routing_provider=routing_provider,
        routing_profile=routing_profile,
        road_version=road_version,
        distance_km=route.distance_km,
        duration_minutes=route.duration_min,
        geometry_polyline=json.dumps(route.polyline, separators=(",", ":")),
        provider_source_url=route.source_url,
        provider_retrieved_at=retrieved_at,
        computed_at=now,
        valid_until=now + timedelta(seconds=max(0.0, max_age_seconds)),
        graph_version_id=graph_version_id,
    )


def edge_from_road_facts(
    *,
    graph_version_id: str,
    from_location_id: int,
    to_location_id: int,
    routing_provider: str,
    routing_profile: str,
    road_version: str,
    distance_km: float,
    duration_minutes: float,
    provider_source_url: str,
    provider_retrieved_at: datetime,
) -> StationEdge:
    return StationEdge(
        graph_version_id=graph_version_id,
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        routing_provider=routing_provider,
        routing_profile=routing_profile,
        road_version=road_version,
        distance_km=distance_km,
        duration_minutes=duration_minutes,
        geometry_polyline=None,
        provider_source_url=provider_source_url,
        provider_retrieved_at=provider_retrieved_at,
        computed_at=datetime.now(UTC),
        valid_until=None,
    )


def route_from_edge(
    edge: StationEdge,
    *,
    start_lat: float,
    start_lng: float,
    end_lat: float,
    end_lng: float,
) -> RoutingResult:
    polyline = json.loads(edge.geometry_polyline) if edge.geometry_polyline else []
    if not isinstance(polyline, list) or len(polyline) < 2:
        polyline = [[start_lat, start_lng], [end_lat, end_lng]]
    return RoutingResult(
        polyline=polyline,
        distance_km=edge.distance_km,
        duration_min=edge.duration_minutes,
        segments=[
            RouteSegmentData(
                from_name="Station",
                to_name="Station",
                distance_km=edge.distance_km,
                duration_min=edge.duration_minutes,
                start_lat=start_lat,
                start_lng=start_lng,
                end_lat=end_lat,
                end_lng=end_lng,
            )
        ],
        provider=edge.routing_provider,
        source_url=edge.provider_source_url or "",
        retrieved_at=edge.provider_retrieved_at,
    )


def _edge_record(model: StationEdgeModel) -> StationEdge:
    return StationEdge(
        id=model.id,
        from_location_id=model.from_location_id,
        to_location_id=model.to_location_id,
        routing_provider=model.routing_provider,
        routing_profile=model.routing_profile,
        road_version=model.road_version,
        distance_km=model.distance_km,
        duration_minutes=model.duration_minutes,
        geometry_polyline=model.geometry_polyline,
        provider_source_url=model.provider_source_url,
        provider_retrieved_at=_utc(model.provider_retrieved_at),
        computed_at=_utc(model.computed_at),
        valid_until=_utc(model.valid_until),
        graph_version_id=model.graph_version_id,
    )


def _graph_version_record(model: StationGraphVersionModel) -> StationGraphVersion:
    return StationGraphVersion(
        id=model.id,
        routing_provider=model.routing_provider,
        routing_profile=model.routing_profile,
        road_version=model.road_version,
        station_dataset_version_id=model.station_dataset_version_id,
        status=model.status,
        started_at=_utc(model.started_at),
        completed_at=_utc(model.completed_at),
        expected_node_count=model.expected_node_count,
        processed_node_count=model.processed_node_count,
        edge_count=model.edge_count,
        last_location_id=model.last_location_id,
        metadata=dict(model.metadata_json or {}),
        failure_reason=model.failure_reason,
    )


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
