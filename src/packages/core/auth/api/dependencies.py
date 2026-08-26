from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.apps.api.bootstrap.config import Settings, get_settings
from src.packages.core.auth.application.service import AuthService
from src.packages.core.auth.infrastructure.models import UserModel
from src.packages.core.auth.infrastructure.repository import SqlAlchemyAuthRepository
from src.packages.core.trips.application.errors import AppError

bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache
def get_auth_service() -> AuthService:
    settings = get_settings()
    repository = SqlAlchemyAuthRepository(settings.database_url)
    if settings.app_env == "test":
        repository.ensure_schema()
    return AuthService(
        repository,
        session_ttl_hours=settings.auth_session_ttl_hours,
        remembered_session_ttl_days=settings.auth_remembered_session_ttl_days,
    )


def require_access_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise AppError(
            code="UNAUTHENTICATED",
            status_code=401,
            message="Bạn cần đăng nhập để tiếp tục.",
        )
    return credentials.credentials


def get_current_user(
    access_token: str = Depends(require_access_token),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserModel:
    return auth_service.authenticate(access_token)


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    settings: Settings = Depends(get_settings),
    auth_service: AuthService = Depends(get_auth_service),
) -> str:
    if credentials is not None and credentials.scheme.lower() == "bearer":
        return auth_service.authenticate(credentials.credentials).id
    # Existing deterministic API tests use this header. It is deliberately
    # unavailable in development and production so it cannot bypass login.
    if settings.app_env == "test":
        return x_user_id or "demo-user"
    raise AppError(
        code="UNAUTHENTICATED",
        status_code=401,
        message="Bạn cần đăng nhập để lập và xem hành trình.",
    )
