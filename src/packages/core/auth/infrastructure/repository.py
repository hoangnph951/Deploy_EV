from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from src.packages.core.auth.infrastructure.models import (
    AuthSessionModel,
    UserModel,
    UserVehicleModel,
)
from src.packages.core.trips.infrastructure.database import Base, build_session_factory
from src.packages.core.trips.infrastructure.models import VehicleProfileModel
from src.packages.core.trips.infrastructure.vehicle_fixtures import load_vehicle_profile_fixtures


class DuplicateEmailError(RuntimeError):
    pass


class DuplicateVehicleError(RuntimeError):
    pass


class SqlAlchemyAuthRepository:
    def __init__(self, database_url: str):
        self._engine, self._session_factory = build_session_factory(database_url)

    def ensure_schema(self) -> None:
        Base.metadata.create_all(self._engine)
        self._seed_vehicle_profiles()

    def _seed_vehicle_profiles(self) -> None:
        with self._session_factory() as session:
            for profile in load_vehicle_profile_fixtures():
                if session.get(VehicleProfileModel, profile.id) is None:
                    session.add(
                        VehicleProfileModel(
                            id=profile.id,
                            version=profile.version,
                            name=profile.name,
                            battery_capacity_kwh=profile.battery_capacity_kwh,
                            usable_capacity_kwh=profile.usable_capacity_kwh,
                            max_charging_power_kw=profile.max_charging_power_kw,
                            connector_type=profile.connector_type,
                            consumption_curve_json=json.loads(profile.consumption_curve_json),
                        )
                    )
            session.commit()

    def create_user(self, user: UserModel) -> UserModel:
        try:
            with self._session_factory() as session:
                session.add(user)
                session.commit()
                session.refresh(user)
                return user
        except IntegrityError as exc:
            raise DuplicateEmailError(user.email) from exc

    def get_user_by_email(self, email: str) -> UserModel | None:
        with self._session_factory() as session:
            return session.scalar(select(UserModel).where(UserModel.email == email))

    def get_user(self, user_id: str) -> UserModel | None:
        with self._session_factory() as session:
            return session.get(UserModel, user_id)

    def create_session(self, auth_session: AuthSessionModel) -> None:
        with self._session_factory() as session:
            session.add(auth_session)
            session.commit()

    def get_active_session_with_user(
        self, token_hash: str, now: datetime
    ) -> tuple[AuthSessionModel, UserModel] | None:
        with self._session_factory() as session:
            row = session.execute(
                select(AuthSessionModel, UserModel)
                .join(UserModel, UserModel.id == AuthSessionModel.user_id)
                .where(
                    AuthSessionModel.token_hash == token_hash,
                    AuthSessionModel.revoked_at.is_(None),
                    AuthSessionModel.expires_at > now,
                    UserModel.is_active.is_(True),
                )
            ).first()
            return (row[0], row[1]) if row else None

    def revoke_session(self, token_hash: str, revoked_at: datetime) -> None:
        with self._session_factory() as session:
            session.execute(
                update(AuthSessionModel)
                .where(AuthSessionModel.token_hash == token_hash)
                .values(revoked_at=revoked_at)
            )
            session.commit()

    def list_vehicle_profiles(self) -> list[VehicleProfileModel]:
        with self._session_factory() as session:
            return list(
                session.scalars(
                    select(VehicleProfileModel)
                    .where(VehicleProfileModel.id.like("vinfast-%"))
                    .order_by(VehicleProfileModel.name.asc())
                )
            )

    def get_vehicle_profile(self, profile_id: str) -> VehicleProfileModel | None:
        with self._session_factory() as session:
            return session.get(VehicleProfileModel, profile_id)

    def list_user_vehicles(self, user_id: str) -> list[tuple[UserVehicleModel, VehicleProfileModel]]:
        with self._session_factory() as session:
            rows = session.execute(
                select(UserVehicleModel, VehicleProfileModel)
                .join(VehicleProfileModel, VehicleProfileModel.id == UserVehicleModel.vehicle_profile_id)
                .where(UserVehicleModel.user_id == user_id)
                .order_by(UserVehicleModel.is_default.desc(), UserVehicleModel.created_at.asc())
            ).all()
            return [(row[0], row[1]) for row in rows]

    def create_user_vehicle(self, vehicle: UserVehicleModel, make_default: bool) -> UserVehicleModel:
        try:
            with self._session_factory() as session:
                existing_count = (
                    session.query(UserVehicleModel)
                    .filter(UserVehicleModel.user_id == vehicle.user_id)
                    .count()
                )
                should_default = make_default or existing_count == 0
                if should_default:
                    session.execute(
                        update(UserVehicleModel)
                        .where(UserVehicleModel.user_id == vehicle.user_id)
                        .values(is_default=False)
                    )
                vehicle.is_default = should_default
                session.add(vehicle)
                session.commit()
                session.refresh(vehicle)
                return vehicle
        except IntegrityError as exc:
            raise DuplicateVehicleError(vehicle.id) from exc

    def set_default_vehicle(self, user_id: str, vehicle_id: str) -> bool:
        with self._session_factory() as session:
            target = session.scalar(
                select(UserVehicleModel).where(
                    UserVehicleModel.id == vehicle_id,
                    UserVehicleModel.user_id == user_id,
                )
            )
            if target is None:
                return False
            session.execute(
                update(UserVehicleModel)
                .where(UserVehicleModel.user_id == user_id)
                .values(is_default=False)
            )
            target.is_default = True
            target.updated_at = datetime.now(UTC)
            session.commit()
            return True

    def user_owns_vehicle_profile(self, user_id: str, profile_id: str) -> bool:
        with self._session_factory() as session:
            return session.scalar(
                select(UserVehicleModel.id).where(
                    UserVehicleModel.user_id == user_id,
                    UserVehicleModel.vehicle_profile_id == profile_id,
                ).limit(1)
            ) is not None
