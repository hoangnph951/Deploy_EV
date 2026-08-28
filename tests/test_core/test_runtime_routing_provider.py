from src.apps.api.bootstrap.config import Settings
from src.packages.core.trips.api import dependencies
from src.packages.core.trips.infrastructure.routing import GoongRoutingProvider


def test_development_runtime_never_uses_straight_line_fixture(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        database_url="sqlite:///:memory:",
        routing_provider="fixture",
        goong_api_key="test-goong-key",
        openai_station_fallback_enabled=False,
        openai_recovery_enabled=False,
        ai_plan_explanation_enabled=False,
    )
    monkeypatch.setattr(dependencies, "get_settings", lambda: settings)
    dependencies.get_trip_service.cache_clear()

    service = dependencies.get_trip_service()
    router = service._planning_orchestrator._runtime.routing_provider

    assert isinstance(router, GoongRoutingProvider)
