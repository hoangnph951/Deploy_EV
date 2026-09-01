from functools import lru_cache

from src.apps.api.bootstrap.config import get_settings
from src.packages.agent.integrations.llm import OpenAISafePlanRanker
from src.packages.agent.planning.graph import build_planning_orchestrator
from src.packages.agent.planning.runtime import (
    PlanningRuntime,
    get_legacy_runtime,
    set_legacy_runtime,
)
from src.packages.core.planning.application.ports import DeterministicPlanRanker
from src.packages.core.policies.application.assumptions import AssumptionSnapshotService
from src.packages.core.policies.application.service import PolicyConfigService
from src.packages.core.policies.infrastructure.sqlalchemy_repository import SqlAlchemyPolicyConfigRepository
from src.packages.core.trips.application.recovery_supervisor import RecoverySupervisor
from src.packages.core.trips.application.service import TripService
from src.packages.core.trips.infrastructure.energy_tool import EnergyTool
from src.packages.core.trips.infrastructure.environment import (
    OpenMeteoEnvironmentProvider,
    StaticEnvironmentProvider,
)
from src.packages.core.trips.infrastructure.feasibility_tool import FeasibilityTool
from src.packages.core.trips.infrastructure.geocoding import (
    GoongGeocoder,
    InMemoryGeocoder,
)
from src.packages.core.trips.infrastructure.goong_places import GoongPlacesClient
from src.packages.core.trips.infrastructure.local_station_catalog_service import (
    LocalStationCatalogService,
)
from src.packages.core.trips.infrastructure.openai_recovery import (
    NullRecoveryAdvisor,
    OpenAIRecoveryAdvisor,
)
from src.packages.core.trips.infrastructure.openai_station_search import (
    OpenAIWebStationDataService,
)
from src.packages.core.trips.infrastructure.routing import (
    GoongRoutingProvider,
    InMemoryRoutingProvider,
)
from src.packages.core.trips.infrastructure.sqlalchemy_repository import SqlAlchemyTripRepository
from src.packages.core.trips.infrastructure.station_catalog_repository import (
    SqlAlchemyStationCatalogRepository,
)
from src.packages.core.trips.infrastructure.station_graph_repository import (
    SqlAlchemyStationEdgeRepository,
)
from src.packages.core.trips.infrastructure.station_service import (
    FallbackStationDataService,
    FixtureStationDataService,
    VinFastStationDataService,
)


def _build_geocoder(settings):
    if settings.app_env == "test" or settings.geocoder_provider == "fixture":
        return InMemoryGeocoder()

    return GoongGeocoder(
        api_key=settings.goong_api_key,
        base_url=settings.goong_api_base_url,
        timeout_seconds=settings.geocoder_timeout_seconds,
        result_limit=settings.geocoder_result_limit,
    )


@lru_cache
def get_goong_places_client() -> GoongPlacesClient:
    settings = get_settings()
    if settings.app_env != "test" and not settings.openai_api_key.strip():
        raise RuntimeError(
            "OPENAI_API_KEY is required for runtime AI decision support."
        )
    return GoongPlacesClient(
        api_key=settings.goong_api_key,
        base_url=settings.goong_api_base_url,
        timeout_seconds=settings.geocoder_timeout_seconds,
    )


def _build_station_service(settings, station_repository, geocoder):
    if settings.station_provider == "fixture":
        station_service = FixtureStationDataService()
    elif settings.station_catalog_db_enabled:
        station_service = LocalStationCatalogService(
            repository=station_repository,
            dataset_max_stale_seconds=settings.station_dataset_max_stale_seconds,
            detail_max_stale_seconds=settings.station_detail_max_stale_seconds,
        )
        # The persisted catalog is an optimization, not the sole source of
        # truth. If it is stale or not hydrated, query the live official
        # locator before falling back to web search.
        station_service = FallbackStationDataService(
            primary=station_service,
            fallback=VinFastStationDataService(
                meta_url=settings.vinfast_locator_meta_url,
                dataset_base_url=settings.vinfast_locator_dataset_base_url,
                detail_base_url=settings.vinfast_locator_detail_base_url,
                timeout_seconds=settings.vinfast_timeout_seconds,
            ),
        )
    else:
        # Keep a live official provider available even when the persisted
        # catalog rollout is disabled or empty. Planning must not depend on a
        # database hydration job to discover the route's charging stations.
        station_service = VinFastStationDataService(
            meta_url=settings.vinfast_locator_meta_url,
            dataset_base_url=settings.vinfast_locator_dataset_base_url,
            detail_base_url=settings.vinfast_locator_detail_base_url,
            timeout_seconds=settings.vinfast_timeout_seconds,
        )
    if settings.openai_station_fallback_enabled and settings.openai_api_key:
        station_service = FallbackStationDataService(
            primary=station_service,
            fallback=OpenAIWebStationDataService(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                model=settings.openai_station_search_model,
                geocoder=geocoder,
                timeout_seconds=settings.openai_station_search_timeout_seconds,
                allowed_domains=tuple(
                    domain.strip()
                    for domain in settings.openai_station_search_allowed_domains.split(",")
                    if domain.strip()
                ),
                max_candidates=settings.openai_station_search_max_candidates,
                evidence_repository=station_repository,
            ),
        )
    return station_service


@lru_cache
def get_trip_service() -> TripService:
    settings = get_settings()
    repository = SqlAlchemyTripRepository(settings.database_url)
    station_repository = SqlAlchemyStationCatalogRepository(settings.database_url)
    policy_repository = SqlAlchemyPolicyConfigRepository(settings.database_url)
    # Runtime databases are managed exclusively by Alembic. Calling
    # create_all() against a shared database can create tables without moving
    # alembic_version, which makes the next migration fail with DuplicateTable.
    if settings.app_env == "test":
        repository.ensure_schema()
        policy_repository.ensure_schema()
    geocoder = _build_geocoder(settings)
    if settings.app_env == "test":
        routing_provider = InMemoryRoutingProvider()
        station_service = FixtureStationDataService()
        environment_provider = StaticEnvironmentProvider()
    else:
        # Straight-line interpolation is a deterministic test fixture, not a
        # road router. Runtime plans must use verified Goong road geometry or
        # fail explicitly when Goong is unavailable.
        routing_provider = GoongRoutingProvider(
            api_key=settings.goong_api_key,
            base_url=settings.goong_api_base_url,
            timeout_seconds=settings.routing_timeout_seconds,
            max_retries=settings.routing_max_retries,
            min_request_interval_seconds=settings.goong_min_request_interval_seconds,
            rate_limit_cooldown_seconds=settings.goong_rate_limit_cooldown_seconds,
        )
        station_service = _build_station_service(settings, station_repository, geocoder)
        environment_provider = (
            StaticEnvironmentProvider()
            if settings.environment_provider == "fixture"
            else OpenMeteoEnvironmentProvider(
                weather_base_url=settings.open_meteo_weather_url,
                elevation_base_url=settings.open_meteo_elevation_url,
                timeout_seconds=settings.open_meteo_timeout_seconds,
            )
        )
    planning_runtime = (
        get_legacy_runtime()
        if settings.app_env == "test"
        else PlanningRuntime(
            routing_provider=routing_provider,
            station_service=station_service,
            environment_provider=environment_provider,
            energy_tool=EnergyTool(),
            feasibility_tool=FeasibilityTool(),
            plan_ranker=(
                OpenAISafePlanRanker(
                    api_key=settings.openai_api_key,
                    model=settings.model_name,
                    timeout_seconds=settings.ai_plan_explanation_timeout_seconds,
                    base_url=settings.openai_base_url or None,
                )
                if settings.app_env != "test"
                else DeterministicPlanRanker()
            ),
            station_edge_repository=SqlAlchemyStationEdgeRepository(
                settings.database_url,
                max_age_seconds=settings.station_graph_edge_max_age_seconds,
                max_outgoing_neighbors=settings.station_graph_max_neighbors,
            ),
            station_graph_enabled=settings.station_graph_enabled,
            station_graph_routing_provider=(
                "OSRM" if settings.station_graph_routing_provider == "osrm" else "GOONG_DIRECTIONS"
            ),
            station_graph_routing_profile=(
                settings.osrm_profile if settings.station_graph_routing_provider == "osrm" else "car"
            ),
            station_graph_road_version=settings.station_graph_road_version,
            station_graph_edge_max_age_seconds=settings.station_graph_edge_max_age_seconds,
        )
    )
    set_legacy_runtime(planning_runtime)
    routing_provider = planning_runtime.routing_provider
    recovery_advisor = NullRecoveryAdvisor()
    if settings.openai_recovery_enabled and settings.openai_api_key:
        recovery_advisor = OpenAIRecoveryAdvisor(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_recovery_model,
            timeout_seconds=settings.openai_recovery_timeout_seconds,
        )
    return TripService(
        geocoder=geocoder,
        repository=repository,
        policy_service=PolicyConfigService(repository=policy_repository),
        assumption_snapshot_service=AssumptionSnapshotService(),
        recovery_supervisor=RecoverySupervisor(
            advisor=recovery_advisor,
            geocoder=geocoder,
            routing_provider=routing_provider,
        ),
        planning_orchestrator=build_planning_orchestrator(planning_runtime),
    )
