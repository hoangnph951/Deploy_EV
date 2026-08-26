from __future__ import annotations

from sqlalchemy import Boolean, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from src.packages.core.trips.infrastructure.database import Base


class PolicyConfigModel(Base):
    __tablename__ = "policy_configs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    reserve_soc_percent: Mapped[float] = mapped_column(Float, nullable=False, default=15.0)
    stale_station_hours_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=24.0)
    route_deviation_km_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=2.0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
