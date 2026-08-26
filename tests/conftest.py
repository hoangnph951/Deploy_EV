import os
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./data/test_app.db"

from src.apps.api.bootstrap.config import get_settings
from src.apps.api.main import app
from src.packages.agent.planning.nodes.planning_nodes import configure_planning_providers
from src.packages.core.auth.api.dependencies import get_auth_service
from src.packages.core.simulator.api.dependencies import get_simulator_service
from src.packages.core.trips.api.dependencies import get_trip_service
from src.packages.core.trips.infrastructure.environment import StaticEnvironmentProvider
from src.packages.core.trips.infrastructure.routing import InMemoryRoutingProvider
from src.packages.core.trips.infrastructure.station_service import FixtureStationDataService


@pytest.fixture(autouse=True)
def deterministic_routing_provider():
    """Keep every planning provider offline and deterministic during tests."""
    configure_planning_providers(
        routing_provider=InMemoryRoutingProvider(),
        station_service=FixtureStationDataService(),
        environment_provider=StaticEnvironmentProvider(),
    )
    yield
    configure_planning_providers(
        routing_provider=InMemoryRoutingProvider(),
        station_service=FixtureStationDataService(),
        environment_provider=StaticEnvironmentProvider(),
    )


@pytest_asyncio.fixture
async def client(tmp_path):
    """Async HTTP client for testing API endpoints."""
    test_db_path = (tmp_path / "test_app.db").resolve()
    os.environ["DATABASE_URL"] = f"sqlite:///{test_db_path.as_posix()}"
    get_settings.cache_clear()
    get_trip_service.cache_clear()
    get_auth_service.cache_clear()
    get_simulator_service.cache_clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    get_trip_service.cache_clear()
    get_auth_service.cache_clear()
    get_simulator_service.cache_clear()
    get_settings.cache_clear()


@pytest.fixture
def mock_llm():
    """Mock LLM to avoid calling OpenAI during tests.

    Usage in test:
        def test_something(mock_llm):
            # LLM calls will return mock response instead of hitting OpenAI
            ...
    """
    mock = AsyncMock()
    mock.ainvoke.return_value = AsyncMock(content="Mocked LLM response")
    return mock
