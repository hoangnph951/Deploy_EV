from __future__ import annotations

from functools import lru_cache

from src.packages.core.replanning.application.runtime import ReplanningRuntimeStore
from src.apps.api.bootstrap.config import get_settings
from src.packages.core.replanning.infrastructure.repository import SqlAlchemyReplanningAuditRepository


@lru_cache
def get_replanning_runtime_store() -> ReplanningRuntimeStore:
    settings = get_settings()
    repository = SqlAlchemyReplanningAuditRepository(
        settings.database_url, ensure_schema=settings.app_env == "test"
    )
    return ReplanningRuntimeStore(audit_repository=repository)
