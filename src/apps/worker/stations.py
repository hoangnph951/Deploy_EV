from __future__ import annotations

import argparse
import json
import logging

from src.apps.api.bootstrap.config import (
    get_settings,
    resolve_station_graph_road_version,
)
from src.packages.core.trips.application.station_graph_builder import StationGraphBuilder
from src.packages.core.trips.application.station_ingestion_service import (
    StationDetailHydrator,
    StationIngestionService,
)
from src.packages.core.trips.infrastructure.cache_backend import (
    InMemoryCacheBackend,
    RedisCacheBackend,
)
from src.packages.core.trips.infrastructure.osrm_routing import OsrmRoutingProvider
from src.packages.core.trips.infrastructure.routing import GoongRoutingProvider
from src.packages.core.trips.infrastructure.station_catalog_repository import (
    SqlAlchemyStationCatalogRepository,
)
from src.packages.core.trips.infrastructure.station_graph_repository import (
    SqlAlchemyStationEdgeRepository,
)
from src.packages.core.trips.infrastructure.vinfast_locator_client import (
    VinFastLocatorClient,
)

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Feature 1 station-catalog jobs")
    parser.add_argument(
        "command",
        choices=("sync-stations", "hydrate-stations", "build-station-graph"),
    )
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--origin-limit",
        type=int,
        help="Bound graph-build origins for a resumable rollout chunk.",
    )
    parser.add_argument(
        "--start-after-location-id",
        type=int,
        help="Resume graph building after this charging-location id.",
    )
    parser.add_argument(
        "--graph-version-id",
        help="Resume an explicit BUILDING graph version.",
    )
    args = parser.parse_args()

    settings = get_settings()
    repository = SqlAlchemyStationCatalogRepository(settings.database_url)
    cache_backend = (
        RedisCacheBackend(settings.redis_url)
        if settings.redis_cache_enabled
        else InMemoryCacheBackend(max_entries=1024)
    )
    client = VinFastLocatorClient(
        meta_url=settings.vinfast_locator_meta_url,
        dataset_base_url=settings.vinfast_locator_dataset_base_url,
        detail_base_url=settings.vinfast_locator_detail_base_url,
        timeout_seconds=settings.vinfast_timeout_seconds,
        max_retries=settings.vinfast_max_retries,
        access_denied_cooldown_seconds=settings.vinfast_access_denied_cooldown_seconds,
        rate_limit_cooldown_seconds=settings.vinfast_rate_limit_cooldown_seconds,
        cache_backend=cache_backend,
    )
    if args.command == "build-station-graph":
        graph_road_version = resolve_station_graph_road_version(settings)
        if settings.station_graph_routing_provider == "osrm":
            routing_provider = OsrmRoutingProvider(
                base_url=settings.osrm_base_url,
                profile=settings.osrm_profile,
                timeout_seconds=settings.osrm_timeout_seconds,
                max_retries=settings.osrm_max_retries,
                max_table_locations=settings.osrm_max_table_locations,
            )
            routing_provider_name = "OSRM"
            routing_profile = settings.osrm_profile
        else:
            routing_provider = GoongRoutingProvider(
                api_key=settings.goong_api_key,
                base_url=settings.goong_api_base_url,
                timeout_seconds=settings.routing_timeout_seconds,
                max_retries=settings.routing_max_retries,
                min_request_interval_seconds=settings.goong_min_request_interval_seconds,
                rate_limit_cooldown_seconds=settings.goong_rate_limit_cooldown_seconds,
                cache_backend=cache_backend,
            )
            routing_provider_name = "GOONG_DIRECTIONS"
            routing_profile = "car"
        try:
            result = StationGraphBuilder(
                catalog_repository=repository,
                edge_repository=SqlAlchemyStationEdgeRepository(
                    settings.database_url,
                    max_age_seconds=settings.station_graph_edge_max_age_seconds,
                    max_outgoing_neighbors=settings.station_graph_max_neighbors,
                ),
                routing_provider=routing_provider,
                provider="VINFAST_OFFICIAL",
                routing_provider_name=routing_provider_name,
                routing_profile=routing_profile,
                road_version=graph_road_version,
                max_neighbors=settings.station_graph_max_neighbors,
                coarse_radius_km=settings.station_graph_coarse_radius_km,
                max_road_leg_km=settings.station_graph_max_road_leg_km,
                edge_max_age_seconds=settings.station_graph_edge_max_age_seconds,
            ).build(
                origin_limit=(
                    args.origin_limit
                    if args.origin_limit is not None
                    else settings.station_graph_build_origin_limit
                ),
                start_after_location_id=args.start_after_location_id,
                graph_version_id=args.graph_version_id,
            )
        finally:
            close_routing_provider = getattr(routing_provider, "close", None)
            if callable(close_routing_provider):
                close_routing_provider()
    elif args.command == "sync-stations":
        result = StationIngestionService(
            repository=repository,
            client=client,
            dataset_refresh_seconds=settings.station_dataset_refresh_seconds,
        ).sync()
    else:
        result = StationDetailHydrator(
            repository=repository,
            client=client,
            detail_max_stale_seconds=settings.station_detail_max_stale_seconds,
        ).hydrate(limit=max(1, args.limit))
    logger.info(
        "station_background_job_completed",
        extra={"job": args.command, "result": result.__dict__},
    )
    print(json.dumps(result.__dict__, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
