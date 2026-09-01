import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse

from src.apps.api.bootstrap.config import get_settings
from src.apps.api.bootstrap.logging import configure_logging
from src.apps.api.routes.auth import router as auth_router
from src.apps.api.routes.chat import router as chat_router
from src.apps.api.routes.places import router as places_router
from src.apps.api.routes.monitoring import (
    capabilities_router as simulator_capabilities_router,
    router as monitoring_router,
)
from src.apps.api.routes.simulation import router as simulation_router
from src.apps.api.routes.replanning import router as replanning_router
from src.apps.api.routes.trips import router as trips_router
from src.packages.core.trips.application.errors import AppError

settings = get_settings()
configure_logging(settings.log_level)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s in %s mode", settings.app_name, settings.app_env)
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="AI20K Agent",
    description="AI Agent built with LangGraph",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(places_router, prefix="/api/v1")
app.include_router(monitoring_router, prefix="/api/v1")
app.include_router(simulator_capabilities_router, prefix="/api/v1")
app.include_router(simulation_router, prefix="/api/v1")
app.include_router(replanning_router, prefix="/api/v1")
app.include_router(trips_router, prefix="/api/v1")


@app.middleware("http")
async def attach_trace_id(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-Id", str(uuid4()))
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["X-Trace-Id"] = trace_id
    return response


@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", str(uuid4()))
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
                "trace_id": trace_id,
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", str(uuid4()))
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed.",
                "details": {"errors": jsonable_encoder(exc.errors())},
                "trace_id": trace_id,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.app_env}
