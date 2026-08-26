from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from src.packages.core.trips.application.station_ingestion_service import (
    StationDetailHydrator,
    StationIngestionService,
)
from src.packages.core.trips.infrastructure.local_station_catalog_service import (
    LocalStationCatalogService,
)
from src.packages.core.trips.infrastructure.station_catalog_repository import (
    SqlAlchemyStationCatalogRepository,
)
from src.packages.core.trips.infrastructure.station_service import StationProviderError
from src.packages.core.trips.infrastructure.vinfast_locator_client import (
    VinFastBulkDataset,
    VinFastLocatorClient,
    VinFastLocatorMetadata,
)


class FakeVinFastClient:
    detail_base_url = "https://example.test/get-locator"

    def __init__(
        self,
        *,
        generation: str = "g1",
        records: list[dict] | None = None,
        retrieved_at: datetime | None = None,
    ):
        self.generation = generation
        self.records = records if records is not None else [_bulk_station("one", 105.1)]
        self.retrieved_at = retrieved_at or datetime.now(UTC)
        self.metadata_calls = 0
        self.bulk_calls = 0
        self.detail_calls = 0

    def fetch_metadata(self):
        self.metadata_calls += 1
        return VinFastLocatorMetadata(
            generation=self.generation,
            full_filename=f"{self.generation}.json",
            source_url="https://example.test/meta.json",
            retrieved_at=self.retrieved_at,
            source_last_modified_at=self.retrieved_at,
            raw_payload={"generation": self.generation, "full": f"{self.generation}.json"},
        )

    def fetch_bulk_dataset(self, metadata):
        self.bulk_calls += 1
        return VinFastBulkDataset(
            generation=metadata.generation,
            source_url=f"https://example.test/{metadata.full_filename}",
            retrieved_at=self.retrieved_at,
            source_last_modified_at=self.retrieved_at,
            checksum=f"checksum-{metadata.generation}",
            records=tuple(self.records),
        )

    def fetch_detail(self, external_id, dataset_generation=None):
        del dataset_generation
        self.detail_calls += 1
        return _detail(external_id, self.retrieved_at), self.retrieved_at


def _bulk_station(external_id: str, longitude: float) -> dict:
    return {
        "entity_id": external_id,
        "store_id": f"station-{external_id}",
        "name": f"Station {external_id}",
        "address": "Test corridor",
        "lat": 21.0,
        "lng": longitude,
        "category_slug": "car_charging_station",
        "charging_publish": True,
        "access_type": "public",
        "charging_status": "ACTIVE",
        "parking_fee": False,
    }


def _detail(external_id: str, updated_at: datetime) -> dict:
    timestamp = updated_at.isoformat().replace("+00:00", "Z")
    return {
        "charging_status": "ACTIVE",
        "data": {
            "id": f"station-{external_id}",
            "name": f"Station {external_id}",
            "address": "Test corridor",
            "access_type": "Public",
            "opening_times": {"twentyfourseven": True},
            "last_updated": timestamp,
            "extra_data": {"depot_status": "ACTIVE", "parking_fee": False},
            "evses": [
                {
                    "id": f"evse-{external_id}",
                    "status": "ACTIVE",
                    "connectors": [
                        {
                            "standard": "IEC_62196_T2_COMBO",
                            "max_electric_power": 60000,
                            "last_updated": timestamp,
                        }
                    ],
                }
            ],
        },
    }


def _repository(tmp_path) -> SqlAlchemyStationCatalogRepository:
    repository = SqlAlchemyStationCatalogRepository(f"sqlite:///{(tmp_path / 'station-catalog.db').as_posix()}")
    repository.ensure_schema()
    return repository


def _sync(repository, client) -> None:
    result = StationIngestionService(
        repository=repository,
        client=client,
        dataset_refresh_seconds=300.0,
    ).sync()
    assert result.status in {"INGESTED", "NOOP"}


def test_ingestion_is_idempotent_for_same_generation(tmp_path) -> None:
    repository = _repository(tmp_path)
    client = FakeVinFastClient(records=[_bulk_station("one", 105.1), _bulk_station("two", 105.2)])
    service = StationIngestionService(
        repository=repository,
        client=client,
        dataset_refresh_seconds=300.0,
    )

    first = service.sync()
    second = service.sync()

    assert first.status == "INGESTED"
    assert first.location_count == 2
    assert second.status == "NOOP"
    assert client.bulk_calls == 1
    assert repository.get_active_dataset_version("VINFAST_OFFICIAL").generation == "g1"


def test_changed_generation_updates_and_marks_removed_station_inactive(tmp_path) -> None:
    repository = _repository(tmp_path)
    first = FakeVinFastClient(records=[_bulk_station("one", 105.1), _bulk_station("two", 105.2)])
    _sync(repository, first)
    second = FakeVinFastClient(generation="g2", records=[_bulk_station("two", 105.25)])
    _sync(repository, second)

    assert repository.get_active_dataset_version("VINFAST_OFFICIAL").generation == "g2"
    assert repository.get_location_detail("VINFAST_OFFICIAL", "one").active is False
    assert repository.get_location_detail("VINFAST_OFFICIAL", "two").longitude == 105.25


def test_malformed_bulk_is_rejected_without_replacing_last_known_good(tmp_path) -> None:
    repository = _repository(tmp_path)
    _sync(repository, FakeVinFastClient())
    malformed = FakeVinFastClient(generation="g2", records=[{"invalid": True}])

    with pytest.raises(StationProviderError) as captured:
        _sync(repository, malformed)

    assert captured.value.code == "PROVIDER_INVALID_SCHEMA"
    assert repository.get_active_dataset_version("VINFAST_OFFICIAL").generation == "g1"


def test_hydration_normalizes_connector_and_planner_reads_only_local_catalog(tmp_path) -> None:
    repository = _repository(tmp_path)
    client = FakeVinFastClient()
    _sync(repository, client)
    before_hydration = client.detail_calls
    hydrator = StationDetailHydrator(
        repository=repository,
        client=client,
        detail_max_stale_seconds=86400.0,
    )

    hydration = hydrator.hydrate(limit=10)
    service = LocalStationCatalogService(
        repository=repository,
        dataset_max_stale_seconds=86400.0,
        detail_max_stale_seconds=86400.0,
    )
    candidates = service.find_station_window(
        polyline=[[21.0, 105.0], [21.0, 105.1], [21.0, 105.2]],
        origin_lat=21.0,
        origin_lng=105.0,
        dest_lat=21.0,
        dest_lng=105.2,
        progress_start_km=0.0,
        progress_end_km=30.0,
        compatible_connectors=("CCS2",),
        max_corridor_buffer_km=5.0,
        max_detour_min=15.0,
        total_route_distance_km=22.0,
        max_detail_candidates=24,
        target_candidate_count=12,
    )

    assert hydration.verified == 1
    assert client.detail_calls == before_hydration + 1
    assert len(candidates) == 1
    assert candidates[0].station_id == "station-one"
    assert candidates[0].connector_types == ["CCS2"]
    assert candidates[0].max_power_kw == 60.0
    assert candidates[0].detail_quality == "VERIFIED"
    assert candidates[0].catalog_location_id is not None
    assert client.detail_calls == before_hydration + 1


def test_partial_station_is_not_eligible_for_primary_planner(tmp_path) -> None:
    repository = _repository(tmp_path)
    _sync(repository, FakeVinFastClient())
    service = LocalStationCatalogService(repository=repository)

    candidates = service.find_station_window(
        polyline=[[21.0, 105.0], [21.0, 105.1], [21.0, 105.2]],
        origin_lat=21.0,
        origin_lng=105.0,
        dest_lat=21.0,
        dest_lng=105.2,
        progress_start_km=0.0,
        progress_end_km=30.0,
        compatible_connectors=("CCS2",),
        max_corridor_buffer_km=5.0,
        max_detour_min=15.0,
        total_route_distance_km=22.0,
        max_detail_candidates=24,
        target_candidate_count=12,
    )

    assert candidates == []


def test_dataset_beyond_hard_max_age_is_unavailable_not_infeasible(tmp_path) -> None:
    repository = _repository(tmp_path)
    old = datetime.now(UTC) - timedelta(days=2)
    _sync(repository, FakeVinFastClient(retrieved_at=old))
    service = LocalStationCatalogService(
        repository=repository,
        dataset_max_stale_seconds=3600.0,
    )

    with pytest.raises(StationProviderError) as captured:
        service.find_corridor_stations(
            polyline=[[21.0, 105.0], [21.0, 105.2]],
            origin_lat=21.0,
            origin_lng=105.0,
            dest_lat=21.0,
            dest_lng=105.2,
        )

    assert captured.value.code == "STATION_DATA_STALE"


def test_sqlite_spatial_fallback_enforces_exact_radius_after_bounding_box(tmp_path) -> None:
    repository = _repository(tmp_path)
    origin = _bulk_station("origin", 105.0)
    near = _bulk_station("near", 105.03)
    near["lat"] = 21.03
    diagonal_outside = _bulk_station("diagonal-outside", 105.085)
    diagonal_outside["lat"] = 21.08
    _sync(
        repository,
        FakeVinFastClient(records=[origin, near, diagonal_outside]),
    )

    nearby = repository.query_nearby_locations(
        provider="VINFAST_OFFICIAL",
        latitude=21.0,
        longitude=105.0,
        radius_km=10.0,
        limit=10,
    )

    assert [station.external_id for station in nearby] == ["origin", "near"]


def test_background_locator_403_is_non_retryable_and_opens_shared_circuit(
    monkeypatch,
) -> None:
    calls = 0

    def denied_get(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return httpx.Response(403)

    monkeypatch.setattr(httpx, "get", denied_get)
    client = VinFastLocatorClient(
        meta_url="https://example.test/meta.json",
        dataset_base_url="https://example.test/locators",
        detail_base_url="https://example.test/get-locator",
        max_retries=4,
    )

    with pytest.raises(StationProviderError) as first:
        client.fetch_metadata()
    with pytest.raises(StationProviderError) as second:
        client.fetch_metadata()

    assert first.value.code == "PROVIDER_ACCESS_DENIED"
    assert first.value.http_status == 403
    assert first.value.retryable is False
    assert second.value.code == "PROVIDER_ACCESS_DENIED"
    assert calls == 1


def test_background_locator_429_preserves_cooldown_and_stops_repeat_call(
    monkeypatch,
) -> None:
    calls = 0

    def limited_get(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "45"})

    monkeypatch.setattr(httpx, "get", limited_get)
    client = VinFastLocatorClient(
        meta_url="https://example.test/meta.json",
        dataset_base_url="https://example.test/locators",
        detail_base_url="https://example.test/get-locator",
        max_retries=4,
        rate_limit_cooldown_seconds=30.0,
    )

    with pytest.raises(StationProviderError) as first:
        client.fetch_metadata()
    with pytest.raises(StationProviderError) as second:
        client.fetch_metadata()

    assert first.value.code == "PROVIDER_RATE_LIMITED"
    assert first.value.retry_after_seconds == 45.0
    assert second.value.code == "PROVIDER_RATE_LIMITED"
    assert 0 < second.value.retry_after_seconds <= 45.0
    assert calls == 1


def test_fresh_last_known_good_remains_plannable_after_upstream_403(tmp_path) -> None:
    repository = _repository(tmp_path)
    client = FakeVinFastClient()
    _sync(repository, client)
    StationDetailHydrator(
        repository=repository,
        client=client,
        detail_max_stale_seconds=86400.0,
    ).hydrate(limit=10)

    class DeniedRefreshClient:
        def fetch_metadata(self):
            raise StationProviderError(
                "denied",
                code="PROVIDER_ACCESS_DENIED",
                http_status=403,
                retryable=False,
            )

    with pytest.raises(StationProviderError) as refresh:
        StationIngestionService(
            repository=repository,
            client=DeniedRefreshClient(),
            dataset_refresh_seconds=300.0,
        ).sync()

    candidates = LocalStationCatalogService(
        repository=repository,
        dataset_max_stale_seconds=86400.0,
        detail_max_stale_seconds=86400.0,
    ).find_station_window(
        polyline=[[21.0, 105.0], [21.0, 105.1], [21.0, 105.2]],
        origin_lat=21.0,
        origin_lng=105.0,
        dest_lat=21.0,
        dest_lng=105.2,
        progress_start_km=0.0,
        progress_end_km=30.0,
        compatible_connectors=("CCS2",),
        max_corridor_buffer_km=5.0,
        max_detour_min=15.0,
        total_route_distance_km=22.0,
    )

    assert refresh.value.code == "PROVIDER_ACCESS_DENIED"
    assert [candidate.station_id for candidate in candidates] == ["station-one"]
