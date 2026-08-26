from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

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
from src.packages.contracts.trips import VehicleProfileSnapshot
from src.packages.core.auth.infrastructure.models import AuthSessionModel, UserModel, UserVehicleModel
from src.packages.core.auth.infrastructure.repository import (
    DuplicateEmailError,
    DuplicateVehicleError,
    SqlAlchemyAuthRepository,
)
from src.packages.core.auth.infrastructure.security import (
    generate_access_token,
    hash_access_token,
    hash_password,
    verify_password,
)
from src.packages.core.trips.application.errors import AppError, NotFoundError
from src.packages.core.trips.infrastructure.models import VehicleProfileModel


class AuthService:
    def __init__(
        self,
        repository: SqlAlchemyAuthRepository,
        *,
        session_ttl_hours: int = 24,
        remembered_session_ttl_days: int = 30,
    ):
        self._repository = repository
        self._session_ttl_hours = session_ttl_hours
        self._remembered_session_ttl_days = remembered_session_ttl_days

    def register(self, request: RegisterRequest) -> AuthTokenResponse:
        now = datetime.now(UTC)
        user = UserModel(
            id=f"usr-{uuid4().hex}",
            full_name=request.full_name,
            email=request.email,
            phone=request.phone,
            password_hash=hash_password(request.password),
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        try:
            self._repository.create_user(user)
        except DuplicateEmailError as exc:
            raise AppError(
                code="EMAIL_ALREADY_EXISTS",
                status_code=409,
                message="Email này đã được sử dụng.",
                details={"field": "email"},
            ) from exc
        return self._issue_session(user, remember_me=False)

    def login(self, request: LoginRequest) -> AuthTokenResponse:
        user = self._repository.get_user_by_email(request.email)
        if user is None or not user.is_active or not verify_password(request.password, user.password_hash):
            raise AppError(
                code="INVALID_CREDENTIALS",
                status_code=401,
                message="Email hoặc mật khẩu không đúng.",
            )
        return self._issue_session(user, remember_me=request.remember_me)

    def authenticate(self, access_token: str) -> UserModel:
        record = self._repository.get_active_session_with_user(
            hash_access_token(access_token), datetime.now(UTC)
        )
        if record is None:
            raise AppError(
                code="UNAUTHENTICATED",
                status_code=401,
                message="Phiên đăng nhập không hợp lệ hoặc đã hết hạn.",
            )
        return record[1]

    def logout(self, access_token: str) -> None:
        self._repository.revoke_session(hash_access_token(access_token), datetime.now(UTC))

    def get_user_response(self, user: UserModel) -> UserResponse:
        return UserResponse(
            id=user.id,
            full_name=user.full_name,
            email=user.email,
            phone=user.phone,
            created_at=user.created_at,
        )

    def list_vehicle_profiles(self) -> VehicleProfileListResponse:
        return VehicleProfileListResponse(
            profiles=[self._vehicle_profile_response(profile) for profile in self._repository.list_vehicle_profiles()]
        )

    def list_user_vehicles(self, user_id: str) -> UserVehicleListResponse:
        return UserVehicleListResponse(
            vehicles=[
                self._user_vehicle_response(vehicle, profile)
                for vehicle, profile in self._repository.list_user_vehicles(user_id)
            ]
        )

    def create_user_vehicle(
        self, user_id: str, request: UserVehicleCreateRequest
    ) -> UserVehicleResponse:
        profile = self._repository.get_vehicle_profile(request.vehicle_profile_id)
        if profile is None:
            raise NotFoundError("Vehicle profile")
        now = datetime.now(UTC)
        try:
            vehicle = self._repository.create_user_vehicle(
                UserVehicleModel(
                    id=f"veh-{uuid4().hex}",
                    user_id=user_id,
                    vehicle_profile_id=profile.id,
                    nickname=request.nickname,
                    license_plate=request.license_plate.upper() if request.license_plate else None,
                    is_default=False,
                    created_at=now,
                    updated_at=now,
                ),
                make_default=request.make_default,
            )
        except DuplicateVehicleError as exc:
            raise AppError(
                code="VEHICLE_ALREADY_EXISTS",
                status_code=409,
                message="Xe với mẫu và biển số này đã có trong tài khoản.",
            ) from exc
        return self._user_vehicle_response(vehicle, profile)

    def set_default_vehicle(self, user_id: str, vehicle_id: str) -> UserVehicleListResponse:
        if not self._repository.set_default_vehicle(user_id, vehicle_id):
            raise NotFoundError("User vehicle")
        return self.list_user_vehicles(user_id)

    def require_owned_vehicle_profile(self, user_id: str, profile_id: str) -> None:
        if not self._repository.user_owns_vehicle_profile(user_id, profile_id):
            raise AppError(
                code="VEHICLE_NOT_REGISTERED",
                status_code=400,
                message="Mẫu xe này chưa được thêm vào tài khoản của bạn.",
                details={"vehicle_profile_id": profile_id},
            )

    def _issue_session(self, user: UserModel, *, remember_me: bool) -> AuthTokenResponse:
        now = datetime.now(UTC)
        expires_at = (
            now + timedelta(days=self._remembered_session_ttl_days)
            if remember_me
            else now + timedelta(hours=self._session_ttl_hours)
        )
        access_token = generate_access_token()
        self._repository.create_session(
            AuthSessionModel(
                id=f"ses-{uuid4().hex}",
                user_id=user.id,
                token_hash=hash_access_token(access_token),
                expires_at=expires_at,
                created_at=now,
                revoked_at=None,
            )
        )
        return AuthTokenResponse(
            access_token=access_token,
            expires_at=expires_at,
            user=self.get_user_response(user),
            needs_vehicle_setup=not self._repository.list_user_vehicles(user.id),
        )

    @staticmethod
    def _vehicle_profile_response(profile: VehicleProfileModel) -> VehicleProfileSnapshot:
        curve = profile.consumption_curve_json
        if isinstance(curve, str):
            curve = json.loads(curve)
        return VehicleProfileSnapshot(
            id=profile.id,
            name=profile.name,
            version=profile.version,
            battery_capacity_kwh=profile.battery_capacity_kwh,
            usable_capacity_kwh=profile.usable_capacity_kwh,
            max_charging_power_kw=profile.max_charging_power_kw,
            connector_type=profile.connector_type,
            baseline_wh_per_km=float(curve["baseline_wh_per_km"]),
            reference_range_km=curve.get("reference_range_km"),
            reference_range_standard=curve.get("reference_range_standard"),
            brochure_range_km=curve.get("brochure_range_km"),
            brochure_range_standard=curve.get("brochure_range_standard"),
            motor_power_kw=curve.get("motor_power_kw"),
            max_torque_nm=curve.get("max_torque_nm"),
            drive_type=curve.get("drive_type"),
            seats=curve.get("seats"),
            curb_weight_kg=curve.get("curb_weight_kg"),
            dimensions_mm=curve.get("dimensions_mm"),
            wheelbase_mm=curve.get("wheelbase_mm"),
            ground_clearance_mm=curve.get("ground_clearance_mm"),
            wheel_size_inch=curve.get("wheel_size_inch"),
            fast_charge_10_70_min=curve.get("fast_charge_10_70_min"),
            official_source_url=curve.get("official_source"),
        )

    def _user_vehicle_response(
        self, vehicle: UserVehicleModel, profile: VehicleProfileModel
    ) -> UserVehicleResponse:
        return UserVehicleResponse(
            id=vehicle.id,
            nickname=vehicle.nickname,
            license_plate=vehicle.license_plate,
            is_default=vehicle.is_default,
            vehicle_profile=self._vehicle_profile_response(profile),
            created_at=vehicle.created_at,
        )
