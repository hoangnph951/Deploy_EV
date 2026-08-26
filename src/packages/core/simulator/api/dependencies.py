from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from src.packages.core.simulator.application.catalog_service import SimulationCatalogService
from src.packages.core.simulator.application.simulator_service import SimulatorService
from src.packages.core.trips.api.dependencies import get_trip_service


@lru_cache
def get_simulator_service() -> SimulatorService:
    # Configure the same runtime routing/station/environment providers used by
    # F1 before a simulation can invoke real-time replanning.
    get_trip_service()
    log_directory = Path.cwd() / "log_F1"
    catalog = SimulationCatalogService(log_directory=log_directory, max_base_logs=15)
    return SimulatorService(catalog)
