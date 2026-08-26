from __future__ import annotations

from sqlalchemy import select

from src.packages.core.policies.domain.entities import DEFAULT_POLICY, PolicyConfig
from src.packages.core.policies.infrastructure.models import PolicyConfigModel
from src.packages.core.trips.infrastructure.database import Base, build_session_factory


class SqlAlchemyPolicyConfigRepository:
    def __init__(self, database_url: str):
        self._engine, self._session_factory = build_session_factory(database_url)

    def ensure_schema(self) -> None:
        Base.metadata.create_all(self._engine)
        self.seed_default_policy()

    def seed_default_policy(self) -> None:
        with self._session_factory() as session:
            exists = session.get(PolicyConfigModel, DEFAULT_POLICY.id)
            if exists is not None:
                return

            session.add(
                PolicyConfigModel(
                    id=DEFAULT_POLICY.id,
                    policy_version=DEFAULT_POLICY.policy_version,
                    reserve_soc_percent=DEFAULT_POLICY.reserve_soc_percent,
                    stale_station_hours_threshold=DEFAULT_POLICY.stale_station_hours_threshold,
                    route_deviation_km_threshold=DEFAULT_POLICY.route_deviation_km_threshold,
                    active=DEFAULT_POLICY.active,
                )
            )
            session.commit()

    def get_active_policy(self) -> PolicyConfig | None:
        with self._session_factory() as session:
            model = session.scalar(
                select(PolicyConfigModel)
                .where(PolicyConfigModel.active.is_(True))
                .order_by(PolicyConfigModel.policy_version.desc())
                .limit(1)
            )
            if model is None:
                return None
            return PolicyConfig(
                id=model.id,
                policy_version=model.policy_version,
                reserve_soc_percent=model.reserve_soc_percent,
                stale_station_hours_threshold=model.stale_station_hours_threshold,
                route_deviation_km_threshold=model.route_deviation_km_threshold,
                active=model.active,
            )
