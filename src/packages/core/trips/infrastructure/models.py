from __future__ import annotations

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, validates

from src.packages.core.trips.infrastructure.database import Base


class VehicleProfileModel(Base):
    __tablename__ = "vehicle_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    battery_capacity_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    usable_capacity_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    max_charging_power_kw: Mapped[float] = mapped_column(Float, nullable=False)
    connector_type: Mapped[str] = mapped_column(String(32), nullable=False)
    consumption_curve_json: Mapped[dict] = mapped_column(JSON, nullable=False)


class TripModel(Base):
    __tablename__ = "trips"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    origin_address: Mapped[str] = mapped_column(Text, nullable=False)
    origin_lat: Mapped[float] = mapped_column(Float, nullable=False)
    origin_lng: Mapped[float] = mapped_column(Float, nullable=False)
    origin_source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    destination_address: Mapped[str] = mapped_column(Text, nullable=False)
    destination_lat: Mapped[float] = mapped_column(Float, nullable=False)
    destination_lng: Mapped[float] = mapped_column(Float, nullable=False)
    destination_source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    initial_soc_percent: Mapped[float] = mapped_column(Float, nullable=False)
    soc_source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    vehicle_profile_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    preference: Mapped[str] = mapped_column(String(32), nullable=False)
    assumptions_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_plan_version: Mapped[int | None] = mapped_column(Integer)


class PlanVersionModel(Base):
    __tablename__ = "plan_versions"
    __table_args__ = (UniqueConstraint("trip_id", "version", name="uq_plan_versions_trip_version"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trip_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("trips.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    base_plan_version: Mapped[int | None] = mapped_column(Integer)
    context_version: Mapped[int | None] = mapped_column(Integer)
    decision_reason: Mapped[str | None] = mapped_column(Text)
    assumptions: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)

    @validates("assumptions")
    def validate_assumptions(self, _key: str, value: dict) -> dict:
        if not isinstance(value, dict):
            raise ValueError("PlanVersion assumptions must be a JSON object.")
        required_fields = {
            "policy_version",
            "reserve_soc_percent",
            "ambient_temperature_c",
            "vehicle_payload_kg",
            "vehicle_profile_version",
            "source",
            "created_at",
        }
        missing_fields = required_fields.difference(value)
        if missing_fields:
            missing = ", ".join(sorted(missing_fields))
            raise ValueError(f"PlanVersion assumptions are missing required fields: {missing}.")
        return value
