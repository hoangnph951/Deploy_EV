from __future__ import annotations

import math
from datetime import UTC, datetime

from sqlalchemy import delete, func, text
from sqlalchemy.orm import load_only

from src.packages.core.trips.application.station_catalog_repository import (
    StationCatalogRepository,
)
from src.packages.core.trips.domain.station_catalog import (
    CatalogStation,
    StationConnectorData,
    StationDatasetVersion,
    StationEvidence,
    StationEvseData,
    StationLocationUpsert,
)
from src.packages.core.trips.infrastructure.database import Base, build_session_factory
from src.packages.core.trips.infrastructure.models import (
    ChargingConnectorModel,
    ChargingDatasetVersionModel,
    ChargingEvseModel,
    ChargingLocationModel,
    StationExternalEvidenceModel,
)
from src.packages.core.trips.infrastructure.routing import haversine_distance_km


class SqlAlchemyStationCatalogRepository(StationCatalogRepository):
    def __init__(self, database_url: str):
        self._engine, self._session_factory = build_session_factory(database_url)

    def ensure_schema(self) -> None:
        Base.metadata.create_all(self._engine)

    def get_active_dataset_version(self, provider: str) -> StationDatasetVersion | None:
        with self._session_factory() as session:
            model = (
                session.query(ChargingDatasetVersionModel)
                .filter(
                    ChargingDatasetVersionModel.provider == provider,
                    ChargingDatasetVersionModel.status == "ACTIVE",
                )
                .one_or_none()
            )
            return _dataset_record(model) if model is not None else None

    def ingest_dataset(
        self,
        version: StationDatasetVersion,
        locations: list[StationLocationUpsert],
    ) -> int:
        if version.status != "ACTIVE":
            raise ValueError("A newly ingested dataset version must be ACTIVE.")
        if not locations:
            raise ValueError("Refusing to activate an empty station dataset.")

        with self._session_factory() as session:
            current = (
                session.query(ChargingDatasetVersionModel)
                .filter(
                    ChargingDatasetVersionModel.provider == version.provider,
                    ChargingDatasetVersionModel.status == "ACTIVE",
                )
                .with_for_update()
                .one_or_none()
            )
            if current is not None and current.generation == version.generation:
                return 0
            if current is not None:
                current.status = "SUPERSEDED"
                session.flush()

            session.add(
                ChargingDatasetVersionModel(
                    id=version.id,
                    provider=version.provider,
                    generation=version.generation,
                    source_url=version.source_url,
                    source_last_modified_at=version.source_last_modified_at,
                    retrieved_at=version.retrieved_at,
                    valid_until=version.valid_until,
                    checksum=version.checksum,
                    status=version.status,
                    metadata_json=version.metadata,
                )
            )
            existing_by_external_id = {
                model.external_id: model
                for model in session.query(ChargingLocationModel)
                .filter(ChargingLocationModel.provider == version.provider)
                .all()
            }
            seen: set[str] = set()
            now = datetime.now(UTC)
            for location in locations:
                seen.add(location.external_id)
                model = existing_by_external_id.get(location.external_id)
                if model is None:
                    model = ChargingLocationModel(
                        provider=version.provider,
                        external_id=location.external_id,
                        dataset_version_id=version.id,
                        name=location.name,
                        address=location.address,
                        category_slug=location.category_slug,
                        access_type=location.access_type,
                        charging_publish=location.charging_publish,
                        station_status=location.station_status,
                        latitude=location.latitude,
                        longitude=location.longitude,
                        location=_point_wkt(location.latitude, location.longitude),
                        source_url=location.source_url,
                        source_updated_at=location.source_updated_at,
                        retrieved_at=location.retrieved_at,
                        raw_payload={"bulk": location.raw_payload},
                        active=True,
                        detail_quality=location.detail_quality,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(model)
                    continue

                existing_payload = dict(model.raw_payload or {})
                existing_payload["bulk"] = location.raw_payload
                model.dataset_version_id = version.id
                model.name = location.name
                model.address = location.address
                model.category_slug = location.category_slug
                model.access_type = location.access_type
                model.charging_publish = location.charging_publish
                model.station_status = location.station_status
                model.latitude = location.latitude
                model.longitude = location.longitude
                model.location = _point_wkt(location.latitude, location.longitude)
                model.retrieved_at = location.retrieved_at
                model.raw_payload = existing_payload
                model.active = True
                if model.detail_quality != "VERIFIED":
                    model.detail_quality = location.detail_quality
                    model.source_url = location.source_url
                    model.source_updated_at = location.source_updated_at
                model.updated_at = now

            for external_id, stale in existing_by_external_id.items():
                if stale.active and external_id not in seen:
                    stale.active = False
                    stale.updated_at = now

            session.commit()
            return len(locations)

    def query_locations_for_planning(
        self,
        *,
        provider: str,
        min_lat: float,
        max_lat: float,
        min_lon: float,
        max_lon: float,
    ) -> list[CatalogStation]:
        with self._session_factory() as session:
            models = (
                session.query(ChargingLocationModel)
                .join(
                    ChargingDatasetVersionModel,
                    ChargingDatasetVersionModel.id == ChargingLocationModel.dataset_version_id,
                )
                .filter(
                    ChargingLocationModel.provider == provider,
                    ChargingLocationModel.active.is_(True),
                    ChargingLocationModel.charging_publish.is_(True),
                    ChargingLocationModel.latitude.between(min_lat, max_lat),
                    ChargingLocationModel.longitude.between(min_lon, max_lon),
                    ChargingDatasetVersionModel.status == "ACTIVE",
                )
                .order_by(ChargingLocationModel.id.asc())
                .all()
            )
            return [self._catalog_station(session, model) for model in models]

    def query_graph_locations(
        self,
        *,
        provider: str,
        dataset_version_id: str | None = None,
        start_after_location_id: int | None = None,
        limit: int | None = None,
    ) -> list[CatalogStation]:
        with self._session_factory() as session:
            query = (
                session.query(ChargingLocationModel, ChargingDatasetVersionModel)
                .options(
                    load_only(
                        ChargingLocationModel.id,
                        ChargingLocationModel.provider,
                        ChargingLocationModel.external_id,
                        ChargingLocationModel.dataset_version_id,
                        ChargingLocationModel.name,
                        ChargingLocationModel.address,
                        ChargingLocationModel.access_type,
                        ChargingLocationModel.station_status,
                        ChargingLocationModel.latitude,
                        ChargingLocationModel.longitude,
                        ChargingLocationModel.source_url,
                        ChargingLocationModel.source_updated_at,
                        ChargingLocationModel.retrieved_at,
                        ChargingLocationModel.active,
                        ChargingLocationModel.detail_quality,
                    ),
                    load_only(
                        ChargingDatasetVersionModel.generation,
                        ChargingDatasetVersionModel.source_last_modified_at,
                        ChargingDatasetVersionModel.retrieved_at,
                    ),
                )
                .join(
                    ChargingDatasetVersionModel,
                    ChargingDatasetVersionModel.id
                    == ChargingLocationModel.dataset_version_id,
                )
                .filter(
                    ChargingLocationModel.provider == provider,
                    ChargingLocationModel.active.is_(True),
                    ChargingLocationModel.charging_publish.is_(True),
                    ChargingLocationModel.detail_quality.in_(("VERIFIED", "PARTIAL")),
                    ChargingLocationModel.latitude.between(-90.0, 90.0),
                    ChargingLocationModel.longitude.between(-180.0, 180.0),
                    ChargingDatasetVersionModel.status == "ACTIVE",
                )
                .order_by(ChargingLocationModel.id.asc())
            )
            if start_after_location_id is not None:
                query = query.filter(ChargingLocationModel.id > start_after_location_id)
            if dataset_version_id is not None:
                query = query.filter(
                    ChargingLocationModel.dataset_version_id == dataset_version_id
                )
            if limit is not None:
                query = query.limit(max(0, limit))
            return [
                _graph_station(model, dataset)
                for model, dataset in query.all()
            ]

    def count_graph_locations(
        self,
        *,
        provider: str,
        dataset_version_id: str,
    ) -> int:
        with self._session_factory() as session:
            return (
                session.query(func.count(ChargingLocationModel.id))
                .join(
                    ChargingDatasetVersionModel,
                    ChargingDatasetVersionModel.id
                    == ChargingLocationModel.dataset_version_id,
                )
                .filter(
                    ChargingLocationModel.provider == provider,
                    ChargingLocationModel.dataset_version_id == dataset_version_id,
                    ChargingLocationModel.active.is_(True),
                    ChargingLocationModel.charging_publish.is_(True),
                    ChargingLocationModel.detail_quality.in_(("VERIFIED", "PARTIAL")),
                    ChargingLocationModel.latitude.between(-90.0, 90.0),
                    ChargingLocationModel.longitude.between(-180.0, 180.0),
                    ChargingDatasetVersionModel.status == "ACTIVE",
                )
                .scalar()
                or 0
            )

    def query_nearby_graph_locations(
        self,
        *,
        provider: str,
        dataset_version_id: str | None = None,
        latitude: float,
        longitude: float,
        radius_km: float,
        limit: int,
    ) -> list[CatalogStation]:
        if self._engine.dialect.name != "postgresql":
            ranked = sorted(
                (
                    (
                        haversine_distance_km(
                            latitude,
                            longitude,
                            station.latitude,
                            station.longitude,
                        ),
                        station,
                    )
                    for station in self.query_graph_locations(
                        provider=provider,
                        dataset_version_id=dataset_version_id,
                    )
                ),
                key=lambda item: (item[0], item[1].location_id),
            )
            return [
                station
                for distance, station in ranked
                if distance <= radius_km
            ][: max(1, limit)]

        point = func.ST_GeogFromText(
            f"SRID=4326;POINT({longitude:.8f} {latitude:.8f})"
        )
        with self._session_factory() as session:
            query = (
                session.query(ChargingLocationModel, ChargingDatasetVersionModel)
                .options(
                    load_only(
                        ChargingLocationModel.id,
                        ChargingLocationModel.provider,
                        ChargingLocationModel.external_id,
                        ChargingLocationModel.dataset_version_id,
                        ChargingLocationModel.name,
                        ChargingLocationModel.address,
                        ChargingLocationModel.access_type,
                        ChargingLocationModel.station_status,
                        ChargingLocationModel.latitude,
                        ChargingLocationModel.longitude,
                        ChargingLocationModel.source_url,
                        ChargingLocationModel.source_updated_at,
                        ChargingLocationModel.retrieved_at,
                        ChargingLocationModel.active,
                        ChargingLocationModel.detail_quality,
                    ),
                    load_only(
                        ChargingDatasetVersionModel.generation,
                        ChargingDatasetVersionModel.source_last_modified_at,
                        ChargingDatasetVersionModel.retrieved_at,
                    ),
                )
                .join(
                    ChargingDatasetVersionModel,
                    ChargingDatasetVersionModel.id
                    == ChargingLocationModel.dataset_version_id,
                )
                .filter(
                    ChargingLocationModel.provider == provider,
                    ChargingLocationModel.active.is_(True),
                    ChargingLocationModel.charging_publish.is_(True),
                    ChargingLocationModel.detail_quality.in_(("VERIFIED", "PARTIAL")),
                    ChargingLocationModel.latitude.between(-90.0, 90.0),
                    ChargingLocationModel.longitude.between(-180.0, 180.0),
                    ChargingDatasetVersionModel.status == "ACTIVE",
                    func.ST_DWithin(
                        ChargingLocationModel.location,
                        point,
                        radius_km * 1000.0,
                    ),
                )
            )
            if dataset_version_id is not None:
                query = query.filter(
                    ChargingLocationModel.dataset_version_id == dataset_version_id
                )
            rows = (
                query.order_by(
                    ChargingLocationModel.location.op("<->")(point),
                    ChargingLocationModel.id,
                )
                .limit(max(1, limit))
                .all()
            )
            return [_graph_station(model, dataset) for model, dataset in rows]

    def query_nearby_graph_locations_batch(
        self,
        *,
        provider: str,
        dataset_version_id: str,
        origin_ids: list[int],
        radius_km: float,
        limit: int,
    ) -> dict[int, list[CatalogStation]]:
        if not origin_ids:
            return {}
        if self._engine.dialect.name != "postgresql":
            origins = self.query_graph_locations(
                provider=provider,
                dataset_version_id=dataset_version_id,
            )
            origin_by_id = {station.location_id: station for station in origins}
            return {
                origin_id: self.query_nearby_graph_locations(
                    provider=provider,
                    dataset_version_id=dataset_version_id,
                    latitude=origin_by_id[origin_id].latitude,
                    longitude=origin_by_id[origin_id].longitude,
                    radius_km=radius_km,
                    limit=limit,
                )
                for origin_id in origin_ids
                if origin_id in origin_by_id
            }

        statement = text(
            """
            SELECT
                origin.id AS origin_id,
                candidate.id,
                candidate.provider,
                candidate.external_id,
                candidate.dataset_version_id,
                candidate.name,
                candidate.address,
                candidate.access_type,
                candidate.station_status,
                candidate.latitude,
                candidate.longitude,
                candidate.source_url,
                candidate.source_updated_at,
                candidate.retrieved_at,
                candidate.active,
                candidate.detail_quality,
                candidate.dataset_generation,
                candidate.dataset_retrieved_at,
                candidate.dataset_source_updated_at
            FROM unnest(CAST(:origin_ids AS bigint[])) AS requested(origin_id)
            JOIN charging_locations AS origin ON origin.id = requested.origin_id
            JOIN LATERAL (
                SELECT
                    location.id,
                    location.provider,
                    location.external_id,
                    location.dataset_version_id,
                    location.name,
                    location.address,
                    location.access_type,
                    location.station_status,
                    location.latitude,
                    location.longitude,
                    location.source_url,
                    location.source_updated_at,
                    location.retrieved_at,
                    location.active,
                    location.detail_quality,
                    dataset.generation AS dataset_generation,
                    dataset.retrieved_at AS dataset_retrieved_at,
                    dataset.source_last_modified_at AS dataset_source_updated_at,
                    location.location <-> origin.location AS knn_distance
                FROM charging_locations AS location
                JOIN charging_dataset_versions AS dataset
                  ON dataset.id = location.dataset_version_id
                WHERE location.provider = :provider
                  AND location.dataset_version_id = :dataset_version_id
                  AND location.active IS TRUE
                  AND location.charging_publish IS TRUE
                  AND location.detail_quality IN ('VERIFIED', 'PARTIAL')
                  AND location.latitude BETWEEN -90.0 AND 90.0
                  AND location.longitude BETWEEN -180.0 AND 180.0
                  AND dataset.status = 'ACTIVE'
                  AND ST_DWithin(location.location, origin.location, :radius_m)
                ORDER BY location.location <-> origin.location, location.id
                LIMIT :candidate_limit
            ) AS candidate ON TRUE
            ORDER BY origin.id, candidate.knn_distance, candidate.id
            """
        )
        grouped: dict[int, list[CatalogStation]] = {
            origin_id: [] for origin_id in origin_ids
        }
        with self._session_factory() as session:
            rows = session.execute(
                statement,
                {
                    "origin_ids": origin_ids,
                    "provider": provider,
                    "dataset_version_id": dataset_version_id,
                    "radius_m": radius_km * 1000.0,
                    "candidate_limit": max(1, limit),
                },
            ).mappings()
            for row in rows:
                grouped[int(row["origin_id"])].append(_graph_station_from_row(row))
        return grouped

    def get_location_detail(self, provider: str, external_id: str) -> CatalogStation | None:
        with self._session_factory() as session:
            model = (
                session.query(ChargingLocationModel)
                .filter(
                    ChargingLocationModel.provider == provider,
                    ChargingLocationModel.external_id == external_id,
                )
                .one_or_none()
            )
            return self._catalog_station(session, model) if model is not None else None

    def query_nearby_locations(
        self,
        *,
        provider: str,
        latitude: float,
        longitude: float,
        radius_km: float,
        limit: int,
    ) -> list[CatalogStation]:
        if self._engine.dialect.name != "postgresql":
            latitude_padding = radius_km / 111.0
            longitude_padding = radius_km / max(
                20.0, 111.0 * math.cos(math.radians(latitude))
            )
            candidates = self.query_locations_for_planning(
                provider=provider,
                min_lat=max(-90.0, latitude - latitude_padding),
                max_lat=min(90.0, latitude + latitude_padding),
                min_lon=max(-180.0, longitude - longitude_padding),
                max_lon=min(180.0, longitude + longitude_padding),
            )
            ranked = sorted(
                (
                    (
                        haversine_distance_km(
                            latitude,
                            longitude,
                            station.latitude,
                            station.longitude,
                        ),
                        station,
                    )
                    for station in candidates
                ),
                key=lambda item: (item[0], item[1].location_id),
            )
            return [
                station
                for distance, station in ranked
                if distance <= radius_km
            ][: max(1, limit)]

        point = func.ST_GeogFromText(
            f"SRID=4326;POINT({longitude:.8f} {latitude:.8f})"
        )
        with self._session_factory() as session:
            models = (
                session.query(ChargingLocationModel)
                .join(
                    ChargingDatasetVersionModel,
                    ChargingDatasetVersionModel.id
                    == ChargingLocationModel.dataset_version_id,
                )
                .filter(
                    ChargingLocationModel.provider == provider,
                    ChargingLocationModel.active.is_(True),
                    ChargingLocationModel.charging_publish.is_(True),
                    ChargingDatasetVersionModel.status == "ACTIVE",
                    func.ST_DWithin(
                        ChargingLocationModel.location,
                        point,
                        radius_km * 1000.0,
                    ),
                )
                .order_by(func.ST_Distance(ChargingLocationModel.location, point))
                .limit(max(1, limit))
                .all()
            )
            return [self._catalog_station(session, model) for model in models]

    def list_locations_for_hydration(
        self,
        *,
        provider: str,
        limit: int,
    ) -> list[CatalogStation]:
        with self._session_factory() as session:
            models = (
                session.query(ChargingLocationModel)
                .filter(
                    ChargingLocationModel.provider == provider,
                    ChargingLocationModel.active.is_(True),
                )
                .order_by(
                    (ChargingLocationModel.detail_quality == "PARTIAL").desc(),
                    ChargingLocationModel.source_updated_at.asc(),
                    ChargingLocationModel.id.asc(),
                )
                .limit(max(1, limit))
                .all()
            )
            return [self._catalog_station(session, model) for model in models]

    def upsert_location_detail(
        self,
        *,
        provider: str,
        external_id: str,
        evses: tuple[StationEvseData, ...],
        detail_quality: str,
        source_url: str,
        source_updated_at: datetime | None,
        retrieved_at: datetime,
        raw_detail: dict,
    ) -> None:
        if detail_quality not in {"VERIFIED", "PARTIAL", "UNVERIFIED"}:
            raise ValueError(f"Unsupported station detail quality: {detail_quality}")
        with self._session_factory() as session:
            location = (
                session.query(ChargingLocationModel)
                .filter(
                    ChargingLocationModel.provider == provider,
                    ChargingLocationModel.external_id == external_id,
                )
                .with_for_update()
                .one_or_none()
            )
            if location is None:
                raise LookupError(external_id)

            evse_ids = [
                row[0]
                for row in session.query(ChargingEvseModel.id)
                .filter(ChargingEvseModel.location_id == location.id)
                .all()
            ]
            if evse_ids:
                session.execute(delete(ChargingConnectorModel).where(ChargingConnectorModel.evse_id.in_(evse_ids)))
            session.execute(delete(ChargingEvseModel).where(ChargingEvseModel.location_id == location.id))

            for evse in evses:
                evse_model = ChargingEvseModel(
                    location_id=location.id,
                    external_evse_id=evse.external_evse_id,
                    depot_status=evse.depot_status,
                    status=evse.status,
                    retrieved_at=evse.retrieved_at,
                    source_updated_at=evse.source_updated_at,
                    raw_payload=evse.raw_payload,
                )
                session.add(evse_model)
                session.flush()
                for connector in evse.connectors:
                    session.add(
                        ChargingConnectorModel(
                            evse_id=evse_model.id,
                            connector_type=connector.connector_type,
                            normalized_connector=connector.normalized_connector,
                            max_electric_power_kw=connector.max_electric_power_kw,
                            raw_payload=connector.raw_payload,
                        )
                    )

            payload = dict(location.raw_payload or {})
            payload["detail"] = raw_detail
            location.raw_payload = payload
            location.detail_quality = detail_quality
            location.source_url = source_url
            location.source_updated_at = source_updated_at
            location.retrieved_at = retrieved_at
            location.updated_at = datetime.now(UTC)
            session.commit()

    def save_external_evidence(self, evidence: StationEvidence) -> None:
        with self._session_factory() as session:
            session.add(
                StationExternalEvidenceModel(
                    location_id=evidence.location_id,
                    provider=evidence.provider,
                    field_name=evidence.field_name,
                    field_value_json=evidence.field_value,
                    source_url=evidence.source_url,
                    retrieved_at=evidence.retrieved_at,
                    source_updated_at=evidence.source_updated_at,
                    verification_status=evidence.verification_status,
                    raw_evidence=evidence.raw_evidence,
                )
            )
            session.commit()

    def downgrade_stale_details(self, *, provider: str, cutoff: datetime) -> int:
        with self._session_factory() as session:
            changed = (
                session.query(ChargingLocationModel)
                .filter(
                    ChargingLocationModel.provider == provider,
                    ChargingLocationModel.active.is_(True),
                    ChargingLocationModel.detail_quality == "VERIFIED",
                    ChargingLocationModel.source_updated_at.is_not(None),
                    ChargingLocationModel.source_updated_at < cutoff,
                )
                .update(
                    {
                        ChargingLocationModel.detail_quality: "PARTIAL",
                        ChargingLocationModel.updated_at: datetime.now(UTC),
                    },
                    synchronize_session=False,
                )
            )
            session.commit()
            return changed

    def _catalog_station(self, session, model: ChargingLocationModel) -> CatalogStation:
        dataset = session.get(ChargingDatasetVersionModel, model.dataset_version_id)
        evse_models = (
            session.query(ChargingEvseModel)
            .filter(ChargingEvseModel.location_id == model.id)
            .order_by(ChargingEvseModel.id.asc())
            .all()
        )
        evses: list[StationEvseData] = []
        for evse in evse_models:
            connector_models = (
                session.query(ChargingConnectorModel)
                .filter(ChargingConnectorModel.evse_id == evse.id)
                .order_by(ChargingConnectorModel.id.asc())
                .all()
            )
            evses.append(
                StationEvseData(
                    external_evse_id=evse.external_evse_id,
                    depot_status=evse.depot_status,
                    status=evse.status,
                    retrieved_at=_utc(evse.retrieved_at),
                    source_updated_at=_utc(evse.source_updated_at),
                    raw_payload=dict(evse.raw_payload or {}),
                    connectors=tuple(
                        StationConnectorData(
                            connector_type=connector.connector_type,
                            normalized_connector=connector.normalized_connector,
                            max_electric_power_kw=connector.max_electric_power_kw,
                            raw_payload=dict(connector.raw_payload or {}),
                        )
                        for connector in connector_models
                    ),
                )
            )
        return CatalogStation(
            location_id=model.id,
            provider=model.provider,
            external_id=model.external_id,
            dataset_version_id=model.dataset_version_id,
            dataset_generation=dataset.generation,
            dataset_retrieved_at=_utc(dataset.retrieved_at),
            dataset_source_updated_at=_utc(dataset.source_last_modified_at),
            name=model.name,
            address=model.address or "",
            access_type=model.access_type,
            station_status=model.station_status,
            latitude=model.latitude,
            longitude=model.longitude,
            source_url=model.source_url,
            source_updated_at=_utc(model.source_updated_at),
            retrieved_at=_utc(model.retrieved_at),
            active=model.active,
            detail_quality=model.detail_quality,
            raw_payload=dict(model.raw_payload or {}),
            evses=tuple(evses),
        )


def _dataset_record(model: ChargingDatasetVersionModel) -> StationDatasetVersion:
    return StationDatasetVersion(
        id=model.id,
        provider=model.provider,
        generation=model.generation,
        source_url=model.source_url,
        source_last_modified_at=_utc(model.source_last_modified_at),
        retrieved_at=_utc(model.retrieved_at),
        valid_until=_utc(model.valid_until),
        checksum=model.checksum,
        status=model.status,
        metadata=dict(model.metadata_json or {}),
    )


def _graph_station(
    model: ChargingLocationModel,
    dataset: ChargingDatasetVersionModel,
) -> CatalogStation:
    return CatalogStation(
        location_id=model.id,
        provider=model.provider,
        external_id=model.external_id,
        dataset_version_id=model.dataset_version_id,
        dataset_generation=dataset.generation,
        dataset_retrieved_at=_utc(dataset.retrieved_at),
        dataset_source_updated_at=_utc(dataset.source_last_modified_at),
        name=model.name,
        address=model.address or "",
        access_type=model.access_type,
        station_status=model.station_status,
        latitude=model.latitude,
        longitude=model.longitude,
        source_url=model.source_url,
        source_updated_at=_utc(model.source_updated_at),
        retrieved_at=_utc(model.retrieved_at),
        active=model.active,
        detail_quality=model.detail_quality,
        raw_payload={},
        evses=(),
    )


def _graph_station_from_row(row) -> CatalogStation:
    return CatalogStation(
        location_id=int(row["id"]),
        provider=row["provider"],
        external_id=row["external_id"],
        dataset_version_id=row["dataset_version_id"],
        dataset_generation=int(row["dataset_generation"]),
        dataset_retrieved_at=_utc(row["dataset_retrieved_at"]),
        dataset_source_updated_at=_utc(row["dataset_source_updated_at"]),
        name=row["name"],
        address=row["address"] or "",
        access_type=row["access_type"],
        station_status=row["station_status"],
        latitude=float(row["latitude"]),
        longitude=float(row["longitude"]),
        source_url=row["source_url"],
        source_updated_at=_utc(row["source_updated_at"]),
        retrieved_at=_utc(row["retrieved_at"]),
        active=bool(row["active"]),
        detail_quality=row["detail_quality"],
        raw_payload={},
        evses=(),
    )


def _point_wkt(latitude: float, longitude: float) -> str:
    return f"SRID=4326;POINT({longitude:.8f} {latitude:.8f})"


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
