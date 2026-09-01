"""Isolated FastAPI composition used by the local F3/F4 evaluation runners."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import Engine

from src.apps.api.bootstrap.config import Settings, get_settings
from src.apps.api.routes.monitoring import (
    capabilities_router as simulator_capabilities_router,
)
from src.apps.api.routes.monitoring import router as monitoring_router
from src.apps.api.routes.replanning import (
    get_replanning_supervisor,
)
from src.apps.api.routes.replanning import (
    router as replanning_router,
)
from src.apps.api.routes.trips import router as trips_router
from src.packages.agent.planning.graph import build_planning_orchestrator
from src.packages.agent.planning.runtime import PlanningRuntime
from src.packages.agent.replanning.fallback import ConservativeSupervisor
from src.packages.agent.replanning.openai_adapter import OpenAISupervisor
from src.packages.core.auth.api.dependencies import get_auth_service
from src.packages.core.auth.application.service import AuthService
from src.packages.core.auth.infrastructure.repository import SqlAlchemyAuthRepository
from src.packages.core.monitoring.api.dependencies import (
    get_monitoring_simulator_service,
)
from src.packages.core.monitoring.application.service import MonitoringSimulatorService
from src.packages.core.planning.application.ports import DeterministicPlanRanker
from src.packages.core.policies.application.assumptions import AssumptionSnapshotService
from src.packages.core.policies.application.service import PolicyConfigService
from src.packages.core.policies.infrastructure.sqlalchemy_repository import (
    SqlAlchemyPolicyConfigRepository,
)
from src.packages.core.replanning.api.dependencies import get_replanning_runtime_store
from src.packages.core.replanning.application.runtime import ReplanningRuntimeStore
from src.packages.core.replanning.infrastructure.repository import (
    SqlAlchemyReplanningAuditRepository,
)
from src.packages.core.trips.api.dependencies import get_trip_service
from src.packages.core.trips.application.errors import AppError
from src.packages.core.trips.application.recovery_supervisor import RecoverySupervisor
from src.packages.core.trips.application.service import TripService
from src.packages.core.trips.infrastructure.energy_tool import EnergyTool
from src.packages.core.trips.infrastructure.environment import StaticEnvironmentProvider
from src.packages.core.trips.infrastructure.feasibility_tool import FeasibilityTool
from src.packages.core.trips.infrastructure.geocoding import InMemoryGeocoder
from src.packages.core.trips.infrastructure.openai_recovery import NullRecoveryAdvisor
from src.packages.core.trips.infrastructure.routing import InMemoryRoutingProvider
from src.packages.core.trips.infrastructure.sqlalchemy_repository import (
    SqlAlchemyTripRepository,
)
from src.packages.core.trips.infrastructure.station_service import (
    FixtureStationDataService,
)

SupervisorMode = Literal["live", "fallback", "timeout"]


class _AlwaysTimeoutResponses:
    def parse(self, **_kwargs):
        raise TimeoutError("controlled evaluation supervisor timeout")


class _AlwaysTimeoutClient:
    def __init__(self) -> None:
        self.responses = _AlwaysTimeoutResponses()


@dataclass
class EvaluationHarness:
    """Owned app dependencies for one isolated evaluation database."""

    app: FastAPI
    settings: Settings
    database_path: Path
    supervisor_mode: SupervisorMode
    supervisor: object
    trip_service: TripService
    monitoring_service: MonitoringSimulatorService
    runtime_store: ReplanningRuntimeStore
    provider_modes: dict[str, str]
    supervisor_supplied: bool
    _engines: tuple[Engine, ...]

    def client(self) -> AsyncClient:
        return AsyncClient(
            transport=ASGITransport(app=self.app),
            base_url="http://evaluation.local",
        )

    def isolated_for(self, case_id: str) -> EvaluationHarness:
        """Create a fresh database and supervisor budget for one golden case."""

        case_token = sha256(case_id.encode("utf-8")).hexdigest()[:12]
        database_path = self.database_path.with_name(
            f"{self.database_path.stem}-{case_token}-{uuid4().hex[:8]}.db"
        )
        return create_evaluation_harness(
            database_path,
            supervisor_mode=self.supervisor_mode,
            supervisor=self.supervisor if self.supervisor_supplied else None,
            settings=self.settings,
        )

    def close(self, *, remove_database: bool = False) -> None:
        """Release SQLite handles owned by this harness."""

        for engine in self._engines:
            engine.dispose()
        if remove_database:
            self.database_path.unlink(missing_ok=True)


def _build_supervisor(
    settings: Settings,
    mode: SupervisorMode,
    supplied_supervisor: object | None,
) -> object:
    if supplied_supervisor is not None:
        return supplied_supervisor
    if mode == "fallback":
        return ConservativeSupervisor()
    if mode == "timeout":
        return OpenAISupervisor(
            api_key="evaluation-timeout-client",
            model=settings.openai_replanning_model,
            client=_AlwaysTimeoutClient(),
            timeout_seconds=settings.openai_replanning_timeout_seconds,
            max_turns=settings.replanning_max_llm_turns,
        )
    if mode == "live":
        return OpenAISupervisor(
            api_key=settings.openai_api_key,
            model=settings.openai_replanning_model,
            base_url=settings.openai_base_url or None,
            timeout_seconds=settings.openai_replanning_timeout_seconds,
            max_turns=settings.replanning_max_llm_turns,
        )
    raise ValueError(f"Unsupported evaluation supervisor mode: {mode}")


def _build_services(database_url: str, settings: Settings):
    trip_repository = SqlAlchemyTripRepository(database_url)
    trip_repository.ensure_schema()
    policy_repository = SqlAlchemyPolicyConfigRepository(database_url)
    policy_repository.ensure_schema()
    auth_repository = SqlAlchemyAuthRepository(database_url)
    auth_repository.ensure_schema()

    geocoder = InMemoryGeocoder()
    routing_provider = InMemoryRoutingProvider()
    station_service = FixtureStationDataService()
    environment_provider = StaticEnvironmentProvider()
    planning_runtime = PlanningRuntime(
        routing_provider=routing_provider,
        station_service=station_service,
        environment_provider=environment_provider,
        energy_tool=EnergyTool(),
        feasibility_tool=FeasibilityTool(),
        plan_ranker=DeterministicPlanRanker(),
    )
    trip_service = TripService(
        geocoder=geocoder,
        repository=trip_repository,
        policy_service=PolicyConfigService(repository=policy_repository),
        assumption_snapshot_service=AssumptionSnapshotService(),
        recovery_supervisor=RecoverySupervisor(
            advisor=NullRecoveryAdvisor(),
            geocoder=geocoder,
            routing_provider=routing_provider,
        ),
        planning_orchestrator=build_planning_orchestrator(planning_runtime),
    )
    auth_service = AuthService(
        auth_repository,
        session_ttl_hours=settings.auth_session_ttl_hours,
        remembered_session_ttl_days=settings.auth_remembered_session_ttl_days,
    )
    monitoring_service = MonitoringSimulatorService(trip_repository)
    audit_repository = SqlAlchemyReplanningAuditRepository(
        database_url,
        ensure_schema=True,
    )
    runtime_store = ReplanningRuntimeStore(audit_repository=audit_repository)
    engines = (
        trip_repository._engine,
        policy_repository._engine,
        auth_repository._engine,
        audit_repository.engine,
    )
    return trip_service, auth_service, monitoring_service, runtime_store, engines


def _install_common_app_contract(app: FastAPI, settings: Settings) -> None:
    @app.middleware("http")
    async def attach_trace_id(request: Request, call_next):
        request.state.trace_id = request.headers.get("X-Trace-Id", str(uuid4()))
        response = await call_next(request)
        response.headers["X-Trace-Id"] = request.state.trace_id
        return response

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "trace_id": getattr(request.state, "trace_id", str(uuid4())),
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed.",
                    "details": {"errors": jsonable_encoder(exc.errors())},
                    "trace_id": getattr(request.state, "trace_id", str(uuid4())),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            },
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.app_env}


def create_evaluation_harness(
    database_path: Path,
    *,
    supervisor_mode: SupervisorMode = "fallback",
    supervisor: object | None = None,
    settings: Settings | None = None,
) -> EvaluationHarness:
    """Compose an isolated API around real repositories, services, and guards."""

    database_path = database_path.resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    configured = settings or Settings(
        app_env="test",
        database_url=f"sqlite:///{database_path.as_posix()}",
        routing_provider="fixture",
        station_provider="fixture",
        environment_provider="fixture",
        geocoder_provider="fixture",
        simulator_fault_injection_enabled=True,
    )
    if configured.app_env != "test":
        configured = configured.model_copy(update={"app_env": "test"})
    database_url = f"sqlite:///{database_path.as_posix()}"
    configured = configured.model_copy(update={"database_url": database_url})
    replanning_supervisor = _build_supervisor(
        configured,
        supervisor_mode,
        supervisor,
    )
    (
        trip_service,
        auth_service,
        monitoring_service,
        runtime_store,
        engines,
    ) = _build_services(database_url, configured)

    app = FastAPI(title="F3/F4 Local Evaluation API", version="1")
    _install_common_app_contract(app, configured)
    app.include_router(monitoring_router, prefix="/api/v1")
    app.include_router(simulator_capabilities_router, prefix="/api/v1")
    app.include_router(replanning_router, prefix="/api/v1")
    app.include_router(trips_router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: configured
    app.dependency_overrides[get_trip_service] = lambda: trip_service
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_monitoring_simulator_service] = lambda: monitoring_service
    app.dependency_overrides[get_replanning_runtime_store] = lambda: runtime_store
    app.dependency_overrides[get_replanning_supervisor] = lambda: replanning_supervisor

    @app.get("/evaluation/probe")
    async def evaluation_probe():
        active_fault = getattr(app.state, "active_fault", None)
        if active_fault == "F1_PROVIDER_FAILURE":
            return JSONResponse(status_code=200, content={"status": "degraded", "outcome": "INSUFFICIENT_EVIDENCE"})
        elif active_fault == "LLM_TIMEOUT":
            return JSONResponse(status_code=200, content={"status": "degraded", "outcome": "SAFE_FALLBACK"})
        return {"status": "ok", "outcome": "HEALTHY"}

    @app.post("/evaluation/fault")
    async def evaluation_fault(request: Request):
        body = await request.json()
        app.state.active_fault = body.get("fault")
        return {"status": "ok", "active_fault": app.state.active_fault}

    harness = EvaluationHarness(
        app=app,
        settings=configured,
        database_path=database_path,
        supervisor_mode=supervisor_mode,
        supervisor=replanning_supervisor,
        trip_service=trip_service,
        monitoring_service=monitoring_service,
        runtime_store=runtime_store,
        provider_modes={
            "routing": "fixture",
            "station": "fixture",
            "environment": "fixture",
            "supervisor": supervisor_mode,
        },
        supervisor_supplied=supervisor is not None,
        _engines=engines,
    )
    app.state.evaluation_harness = harness
    return harness


def create_app() -> FastAPI:
    """Uvicorn factory using an explicit evaluation database and supervisor mode."""

    database_value = os.environ.get(
        "EVALUATION_DATABASE_PATH",
        "eval/results/local_app.db",
    )
    supervisor_mode = os.environ.get("EVALUATION_SUPERVISOR_MODE", "fallback")
    if supervisor_mode not in {"live", "fallback", "timeout"}:
        raise ValueError("EVALUATION_SUPERVISOR_MODE must be live, fallback, or timeout")
    return create_evaluation_harness(
        Path(database_value),
        supervisor_mode=supervisor_mode,
    ).app
