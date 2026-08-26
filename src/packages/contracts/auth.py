from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from src.packages.contracts.trips import VehicleProfileSnapshot


class RegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=120)
    email: str = Field(..., min_length=5, max_length=254)
    phone: str | None = Field(default=None, max_length=24)
    password: str = Field(..., min_length=8, max_length=128)
    password_confirmation: str = Field(..., min_length=8, max_length=128)
    accepted_terms: bool

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        local, separator, domain = normalized.partition("@")
        if not separator or not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("Email không hợp lệ.")
        return normalized

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        cleaned = value.strip()
        allowed = set("+0123456789 -().")
        if any(character not in allowed for character in cleaned):
            raise ValueError("Số điện thoại chứa ký tự không hợp lệ.")
        return cleaned

    @model_validator(mode="after")
    def validate_registration(self) -> RegisterRequest:
        if self.password != self.password_confirmation:
            raise ValueError("Mật khẩu xác nhận không khớp.")
        if not self.accepted_terms:
            raise ValueError("Bạn cần đồng ý với điều khoản sử dụng.")
        if not any(character.islower() for character in self.password):
            raise ValueError("Mật khẩu cần có ít nhất một chữ thường.")
        if not any(character.isupper() for character in self.password):
            raise ValueError("Mật khẩu cần có ít nhất một chữ hoa.")
        if not any(character.isdigit() for character in self.password):
            raise ValueError("Mật khẩu cần có ít nhất một chữ số.")
        return self


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=1, max_length=128)
    remember_me: bool = False

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        local, separator, domain = normalized.partition("@")
        if not separator or not local or "." not in domain:
            raise ValueError("Email không hợp lệ.")
        return normalized


class UserResponse(BaseModel):
    id: str
    full_name: str
    email: str
    phone: str | None = None
    created_at: datetime


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserResponse
    needs_vehicle_setup: bool


class UserVehicleCreateRequest(BaseModel):
    vehicle_profile_id: str = Field(..., min_length=1, max_length=64)
    nickname: str | None = Field(default=None, max_length=80)
    license_plate: str | None = Field(default=None, max_length=24)
    make_default: bool = True

    @field_validator("nickname", "license_plate")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return " ".join(value.split())


class UserVehicleResponse(BaseModel):
    id: str
    nickname: str | None = None
    license_plate: str | None = None
    is_default: bool
    vehicle_profile: VehicleProfileSnapshot
    created_at: datetime


class VehicleProfileListResponse(BaseModel):
    profiles: list[VehicleProfileSnapshot]


class UserVehicleListResponse(BaseModel):
    vehicles: list[UserVehicleResponse]
