from __future__ import annotations

import math
from datetime import UTC, datetime

from src.packages.contracts.trips import DataProvenance
from src.packages.core.trips.application.station_catalog_repository import (
    StationCatalogRepository,
)
from src.packages.core.trips.domain.station_catalog import CatalogStation
from src.packages.core.trips.infrastructure.observability import metrics
from src.packages.core.trips.infrastructure.routing import haversine_distance_km
from src.packages.core.trips.infrastructure.station_service import (
    CandidateStation,
    StationProviderError,
    _polyline_distance_km,
    _rank_window_candidates,
    _sample_route_with_progress,
)


class LocalStationCatalogService:
    """StationService backed only by the persisted local station catalog."""

    def __init__(
        self,
        *,
        repository: StationCatalogRepository,
        provider: str = "VINFAST_OFFICIAL",
        dataset_max_stale_seconds: float = 86400.0,
        detail_max_stale_seconds: float = 86400.0,
        freshness_threshold_hours: float = 24.0,
        max_detail_candidates: int = 36,
    ):
        self._repository = repository
        self._provider = provider
        self._dataset_max_stale_seconds = max(1.0, dataset_max_stale_seconds)
        self._detail_max_stale_seconds = max(1.0, detail_max_stale_seconds)
        self._freshness_threshold_hours = max(0.01, freshness_threshold_hours)
        self._max_detail_candidates = max(4, min(max_detail_candidates, 60))

    def find_corridor_stations(
        self,
        polyline: list[list[float]],
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        max_corridor_buffer_km: float = 15.0,
        max_detour_min: float = 15.0,
        required_connector: str = "CCS2",
        total_route_distance_km: float | None = None,
        origin_name: str = "Origin",
        dest_name: str = "Destination",
    ) -> list[CandidateStation]:
        del origin_lat, origin_lng, dest_lat, dest_lng, origin_name, dest_name
        if not polyline:
            return []
        coarse = self._find_coarse_candidates(
            polyline=polyline,
            max_corridor_buffer_km=max_corridor_buffer_km,
            max_detour_min=max_detour_min,
        )
        if total_route_distance_km is not None and coarse:
            geometry_distance_km = _polyline_distance_km(polyline)
            if geometry_distance_km > 0:
                scale = total_route_distance_km / geometry_distance_km
                for item in coarse:
                    item["distance_from_origin_km"] *= scale
        shortlisted = self._distribute_candidates_along_route(coarse)
        candidates = [
            candidate for item in shortlisted if (candidate := self._materialize(item, required_connector)) is not None
        ]
        return sorted(candidates, key=lambda station: station.distance_from_origin_km)

    def find_station_window(self, **kwargs) -> list[CandidateStation]:
        polyline = kwargs["polyline"]
        if not polyline:
            return []
        coarse = self._find_coarse_candidates(
            polyline=polyline,
            max_corridor_buffer_km=kwargs["max_corridor_buffer_km"],
            max_detour_min=kwargs["max_detour_min"],
        )
        geometry_distance_km = _polyline_distance_km(polyline)
        if geometry_distance_km > 0:
            scale = kwargs["total_route_distance_km"] / geometry_distance_km
            for item in coarse:
                item["distance_from_origin_km"] *= scale

        start = kwargs["progress_start_km"]
        end = kwargs["progress_end_km"]
        origin_radius = kwargs.get("origin_radius_km")
        eligible = []
        for item in coarse:
            station: CatalogStation = item["catalog_station"]
            in_progress_window = start <= item["distance_from_origin_km"] <= end
            in_origin_radius = bool(
                origin_radius is not None
                and haversine_distance_km(
                    kwargs["origin_lat"],
                    kwargs["origin_lng"],
                    station.latitude,
                    station.longitude,
                )
                <= origin_radius
            )
            if in_progress_window or in_origin_radius:
                eligible.append(item)
        eligible.sort(
            key=lambda item: (
                item["status"] != "ACTIVE",
                -item["distance_from_origin_km"],
                item["distance_to_route_km"],
            )
        )

        max_details = max(1, min(int(kwargs.get("max_detail_candidates", 48)), 96))
        target = max(1, min(int(kwargs.get("target_candidate_count", 8)), 24))
        connectors = tuple(item.upper() for item in kwargs["compatible_connectors"])
        accepted: dict[str, CandidateStation] = {}
        for offset in range(0, min(len(eligible), max_details), 8):
            batch = eligible[offset : min(offset + 8, max_details)]
            for item in batch:
                for connector in connectors:
                    candidate = self._materialize(
                        item,
                        connector,
                        freshness_threshold_hours=kwargs.get(
                            "stale_station_hours_threshold",
                            self._freshness_threshold_hours,
                        ),
                    )
                    if candidate is not None:
                        accepted.setdefault(candidate.station_id, candidate)
                        break
            if len(accepted) >= target:
                break
        return _rank_window_candidates(list(accepted.values()), end)

    def _find_coarse_candidates(
        self,
        *,
        polyline: list[list[float]],
        max_corridor_buffer_km: float,
        max_detour_min: float,
    ) -> list[dict]:
        dataset = self._repository.get_active_dataset_version(self._provider)
        if dataset is None:
            raise StationProviderError(
                "No active local station dataset is available.",
                code="STATION_DATA_UNAVAILABLE",
            )
        dataset_age = (datetime.now(UTC) - _utc(dataset.retrieved_at)).total_seconds()
        metrics.increment("station_catalog_queries_total", provider=self._provider)
        metrics.gauge(
            "station_dataset_age_seconds", dataset_age, provider=self._provider
        )
        metrics.gauge(
            "station_dataset_generation",
            1,
            provider=self._provider,
            generation=dataset.generation or "unknown",
        )
        if dataset_age > self._dataset_max_stale_seconds:
            raise StationProviderError(
                "The active local station dataset exceeded its hard max age.",
                code="STATION_DATA_STALE",
            )

        sampled = _sample_route_with_progress(polyline, 300)
        latitude_padding = max_corridor_buffer_km / 111.0
        mean_lat = sum(point[0] for point in polyline) / len(polyline)
        longitude_padding = max_corridor_buffer_km / max(
            20.0,
            111.0 * math.cos(math.radians(mean_lat)),
        )
        min_lat = min(point[0] for point in polyline) - latitude_padding
        max_lat = max(point[0] for point in polyline) + latitude_padding
        min_lon = min(point[1] for point in polyline) - longitude_padding
        max_lon = max(point[1] for point in polyline) + longitude_padding
        stations = self._repository.query_locations_for_planning(
            provider=self._provider,
            min_lat=min_lat,
            max_lat=max_lat,
            min_lon=min_lon,
            max_lon=max_lon,
        )

        candidates: list[dict] = []
        for station in stations:
            status = str(station.station_status or "").upper()
            if status not in {"ACTIVE", "BUSY"}:
                continue
            nearest = min(
                sampled,
                key=lambda route_point: haversine_distance_km(
                    station.latitude,
                    station.longitude,
                    route_point[0],
                    route_point[1],
                ),
            )
            distance_to_route = haversine_distance_km(
                station.latitude,
                station.longitude,
                nearest[0],
                nearest[1],
            )
            if distance_to_route > max_corridor_buffer_km:
                continue
            detour_distance_km = distance_to_route * 2.0
            detour_duration_min = detour_distance_km / 40.0 * 60.0
            if detour_duration_min > max_detour_min:
                continue
            candidates.append(
                {
                    "entity_id": station.external_id,
                    "status": status,
                    "distance_to_route_km": distance_to_route,
                    "distance_from_origin_km": nearest[2],
                    "detour_distance_km": detour_distance_km,
                    "detour_duration_min": detour_duration_min,
                    "catalog_station": station,
                }
            )
        return candidates

    def _materialize(
        self,
        item: dict,
        required_connector: str,
        *,
        freshness_threshold_hours: float | None = None,
    ) -> CandidateStation | None:
        station: CatalogStation = item["catalog_station"]
        if station.detail_quality != "VERIFIED":
            return None
        source_updated_at = station.source_updated_at or station.dataset_source_updated_at
        if source_updated_at is None:
            return None
        detail_age_seconds = (datetime.now(UTC) - _utc(source_updated_at)).total_seconds()
        if detail_age_seconds > self._detail_max_stale_seconds:
            return None

        compatible = [
            connector
            for evse in station.evses
            for connector in evse.connectors
            if connector.normalized_connector == required_connector.upper() and connector.max_electric_power_kw > 0
        ]
        if not compatible:
            return None
        best_power = max(connector.max_electric_power_kw for connector in compatible)
        best = next(connector for connector in compatible if connector.max_electric_power_kw == best_power)
        port_count = sum(
            1
            for connector in compatible
            if connector.normalized_connector == best.normalized_connector
            and connector.max_electric_power_kw == best_power
        )

        payload = station.raw_payload
        bulk = payload.get("bulk") if isinstance(payload.get("bulk"), dict) else {}
        detail = payload.get("detail") if isinstance(payload.get("detail"), dict) else {}
        nested = detail.get("data") if isinstance(detail.get("data"), dict) else {}
        station_updated_at = _station_updated_at(station)
        freshness_age_hours = (
            (datetime.now(UTC) - station_updated_at).total_seconds() / 3600.0
            if station_updated_at is not None
            else float("inf")
        )
        nested_parking_fee = (nested.get("extra_data") or {}).get("parking_fee")
        summary_parking_fee = bulk.get("parking_fee")
        parking_fee = (
            bool(nested_parking_fee or summary_parking_fee)
            if nested_parking_fee is not None or summary_parking_fee is not None
            else None
        )
        freshness_threshold = (
            self._freshness_threshold_hours
            if freshness_threshold_hours is None
            else max(0.01, float(freshness_threshold_hours))
        )
        return CandidateStation(
            station_id=str(nested.get("id") or bulk.get("store_id") or bulk.get("code") or station.external_id),
            name=str(nested.get("name") or station.name),
            lat=station.latitude,
            lon=station.longitude,
            address=str(nested.get("address") or station.address),
            connector_types=[best.normalized_connector],
            max_power_kw=round(best_power, 1),
            detour_distance_km=round(item["detour_distance_km"], 2),
            detour_duration_min=round(item["detour_duration_min"], 1),
            freshness=("FRESH" if freshness_age_hours <= freshness_threshold else "STALE"),
            distance_from_origin_km=round(item["distance_from_origin_km"], 2),
            connector_standard=best.connector_type,
            port_count=max(1, port_count),
            station_status=str(station.station_status or "ACTIVE").upper(),
            opening_24_7=(nested.get("opening_times") or {}).get("twentyfourseven"),
            access_type=str(nested.get("access_type") or station.access_type or "Public"),
            parking_fee=parking_fee,
            station_updated_at=station_updated_at,
            provenance=DataProvenance(
                kind="STATION_DETAIL",
                source="VINFAST_OFFICIAL",
                source_url=station.source_url or "",
                retrieved_at=_utc(station.retrieved_at),
                source_updated_at=source_updated_at,
                version=station.dataset_generation,
                generation=station.dataset_generation,
                served_at=datetime.now(UTC),
            ),
            catalog_location_id=station.location_id,
            detail_quality="VERIFIED",
        )

    def _distribute_candidates_along_route(self, candidates: list[dict]) -> list[dict]:
        if len(candidates) <= self._max_detail_candidates:
            return sorted(candidates, key=lambda item: item["distance_from_origin_km"])
        selected: list[dict] = []
        selected_ids: set[str] = set()

        def add(item: dict) -> None:
            entity_id = item["entity_id"]
            if entity_id not in selected_ids and len(selected) < self._max_detail_candidates:
                selected.append(item)
                selected_ids.add(entity_id)

        origin_quota = max(8, self._max_detail_candidates // 3)
        origin_candidates = sorted(
            (item for item in candidates if item["distance_from_origin_km"] <= 10.0),
            key=lambda item: (
                item["status"] != "ACTIVE",
                item["distance_to_route_km"],
                item["distance_from_origin_km"],
            ),
        )
        for item in origin_candidates[:origin_quota]:
            add(item)
        max_progress = max(item["distance_from_origin_km"] for item in candidates)
        target_bucket_count = max(1, self._max_detail_candidates - len(selected))
        bucket_width_km = max(5.0, max_progress / target_bucket_count)
        buckets: dict[int, list[dict]] = {}
        for candidate in candidates:
            bucket = int(candidate["distance_from_origin_km"] // bucket_width_km)
            buckets.setdefault(bucket, []).append(candidate)
        for items in buckets.values():
            items.sort(
                key=lambda item: (
                    item["status"] != "ACTIVE",
                    item["distance_to_route_km"],
                    item["distance_from_origin_km"],
                )
            )
        rank = 0
        while len(selected) < self._max_detail_candidates:
            added = False
            for bucket in sorted(buckets):
                items = buckets[bucket]
                if rank < len(items):
                    before = len(selected)
                    add(items[rank])
                    added = added or len(selected) > before
                if len(selected) >= self._max_detail_candidates:
                    break
            if not added:
                break
            rank += 1
        return sorted(selected, key=lambda item: item["distance_from_origin_km"])


class DisabledStationCatalogService:
    """Fail-closed service used when the local catalog rollout flag is disabled."""

    def find_corridor_stations(self, *_args, **_kwargs) -> list[CandidateStation]:
        raise StationProviderError(
            "The local station catalog rollout flag is disabled.",
            code="STATION_CATALOG_DISABLED",
        )

    def find_station_window(self, **_kwargs) -> list[CandidateStation]:
        raise StationProviderError(
            "The local station catalog rollout flag is disabled.",
            code="STATION_CATALOG_DISABLED",
        )


def _station_updated_at(station: CatalogStation) -> datetime | None:
    nested = station.raw_payload.get("detail", {}).get("data", {})
    raw = nested.get("last_updated") if isinstance(nested, dict) else None
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            pass
    return _utc(station.source_updated_at or station.dataset_source_updated_at)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
