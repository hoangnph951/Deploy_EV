from functools import lru_cache

from src.apps.api.bootstrap.config import get_settings
from src.packages.contracts.monitoring import MonitoringThresholds
from src.packages.core.monitoring.application.service import MonitoringSimulatorService
from src.packages.core.trips.infrastructure.sqlalchemy_repository import SqlAlchemyTripRepository


@lru_cache
def get_monitoring_simulator_service() -> MonitoringSimulatorService:
    settings = get_settings()
    return MonitoringSimulatorService(
        SqlAlchemyTripRepository(settings.database_url),
        MonitoringThresholds(
            max_off_route_distance_km=settings.monitoring_max_off_route_distance_km,
            max_soc_drop_deviation_percent=settings.monitoring_max_soc_drop_deviation_percent,
            max_telemetry_silent_seconds=settings.monitoring_max_telemetry_silent_seconds,
        ),
    )
