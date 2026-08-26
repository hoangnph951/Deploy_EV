from fastapi import APIRouter, Depends, Response, status

from src.packages.contracts.auth import (
    AuthTokenResponse,
    LoginRequest,
    RegisterRequest,
    UserResponse,
    UserVehicleCreateRequest,
    UserVehicleListResponse,
    UserVehicleResponse,
    VehicleProfileListResponse,
)
from src.packages.contracts.errors import ErrorEnvelope
from src.packages.core.auth.api.dependencies import (
    get_auth_service,
    get_current_user,
    require_access_token,
)
from src.packages.core.auth.application.service import AuthService
from src.packages.core.auth.infrastructure.models import UserModel

router = APIRouter(tags=["authentication"])


@router.post(
    "/auth/register",
    response_model=AuthTokenResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorEnvelope}},
)
def register(
    body: RegisterRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthTokenResponse:
    return auth_service.register(body)


@router.post(
    "/auth/login",
    response_model=AuthTokenResponse,
    responses={401: {"model": ErrorEnvelope}},
)
def login(
    body: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthTokenResponse:
    return auth_service.login(body)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    access_token: str = Depends(require_access_token),
    auth_service: AuthService = Depends(get_auth_service),
) -> Response:
    auth_service.logout(access_token)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/auth/me", response_model=UserResponse)
def get_me(
    user: UserModel = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserResponse:
    return auth_service.get_user_response(user)


@router.get("/vehicle-profiles", response_model=VehicleProfileListResponse, tags=["vehicles"])
def list_vehicle_profiles(
    auth_service: AuthService = Depends(get_auth_service),
) -> VehicleProfileListResponse:
    return auth_service.list_vehicle_profiles()


@router.get("/me/vehicles", response_model=UserVehicleListResponse, tags=["vehicles"])
def list_my_vehicles(
    user: UserModel = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserVehicleListResponse:
    return auth_service.list_user_vehicles(user.id)


@router.post(
    "/me/vehicles",
    response_model=UserVehicleResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["vehicles"],
)
def add_my_vehicle(
    body: UserVehicleCreateRequest,
    user: UserModel = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserVehicleResponse:
    return auth_service.create_user_vehicle(user.id, body)


@router.patch(
    "/me/vehicles/{vehicle_id}/default",
    response_model=UserVehicleListResponse,
    tags=["vehicles"],
)
def make_vehicle_default(
    vehicle_id: str,
    user: UserModel = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserVehicleListResponse:
    return auth_service.set_default_vehicle(user.id, vehicle_id)
