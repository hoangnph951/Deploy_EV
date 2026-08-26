from src.apps.api.bootstrap.config import (
    Settings,
    resolve_station_graph_road_version,
)
from src.packages.agent.planning.runtime import get_legacy_runtime
from src.packages.core.trips.api import dependencies
from src.packages.core.trips.api.dependencies import _build_station_service
from src.packages.core.trips.infrastructure.geocoding import InMemoryGeocoder
from src.packages.core.trips.infrastructure.local_station_catalog_service import (
    DisabledStationCatalogService,
    LocalStationCatalogService,
)
from src.packages.core.trips.infrastructure.station_catalog_repository import (
    SqlAlchemyStationCatalogRepository,
)


def test_production_station_runtime_reads_local_catalog_not_vinfast_http(tmp_path) -> None:
    settings = Settings(
        app_env="production",
        database_url=f"sqlite:///{(tmp_path / 'runtime.db').as_posix()}",
        station_provider="vinfast",
        station_catalog_db_enabled=True,
        openai_station_fallback_enabled=False,
    )
    repository = SqlAlchemyStationCatalogRepository(settings.database_url)

    service = _build_station_service(settings, repository, InMemoryGeocoder())

    assert isinstance(service, LocalStationCatalogService)


def test_disabled_catalog_fails_closed_instead_of_using_runtime_http(tmp_path) -> None:
    settings = Settings(
        app_env="production",
        database_url=f"sqlite:///{(tmp_path / 'runtime.db').as_posix()}",
        station_provider="vinfast",
        station_catalog_db_enabled=False,
        openai_station_fallback_enabled=False,
    )
    repository = SqlAlchemyStationCatalogRepository(settings.database_url)

    service = _build_station_service(settings, repository, InMemoryGeocoder())

    assert isinstance(service, DisabledStationCatalogService)


def test_osrm_road_version_is_bound_to_prepared_dataset_file(tmp_path) -> None:
    road_version_file = tmp_path / "road-version.txt"
    settings = Settings(
        station_graph_routing_provider="osrm",
        station_graph_road_version="fallback-version",
        osrm_road_version_file=str(road_version_file),
    )

    assert resolve_station_graph_road_version(settings) == "fallback-version"

    road_version_file.write_text(
        "osrm-26.6.5-debian-driving-vietnam-checksum\n",
        encoding="utf-8",
    )

    assert (
        resolve_station_graph_road_version(settings)
        == "osrm-26.6.5-debian-driving-vietnam-checksum"
    )


def test_api_runtime_configures_f4_compatibility_graph_with_live_goong_key(
    tmp_path,
    monkeypatch,
) -> None:
    settings = Settings(
        app_env="production",
        database_url=f"sqlite:///{(tmp_path / 'runtime.db').as_posix()}",
        geocoder_provider="fixture",
        routing_provider="goong",
        goong_api_key="configured-server-key",
        station_provider="fixture",
        openai_station_fallback_enabled=False,
        openai_recovery_enabled=False,
    )
    monkeypatch.setattr(dependencies, "get_settings", lambda: settings)
    dependencies.get_trip_service.cache_clear()

    try:
        dependencies.get_trip_service()
        provider = get_legacy_runtime().routing_provider

        assert provider.__class__.__name__ == "GoongRoutingProvider"
        assert provider._api_key == "configured-server-key"
    finally:
        dependencies.get_trip_service.cache_clear()
