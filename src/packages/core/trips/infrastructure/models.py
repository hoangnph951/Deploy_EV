from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, validates
from sqlalchemy.types import UserDefinedType

from src.packages.core.trips.infrastructure.database import Base


class GeographyPoint(UserDefinedType):
    """PostGIS geography point with a SQLite text variant for tests."""

    cache_ok = True

    def get_col_spec(self, **_kwargs) -> str:
        return "GEOGRAPHY(POINT, 4326)"


JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")
BIGINT_PK = BigInteger().with_variant(Integer(), "sqlite")


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
    __table_args__ = (
        UniqueConstraint(
            "trip_id",
            "version",
            "rank",
            name="uq_plan_versions_trip_version_rank",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trip_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("trips.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    planning_run_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("planning_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    strategy: Mapped[str] = mapped_column(String(32), nullable=False, default="BALANCED")
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    base_plan_version: Mapped[int | None] = mapped_column(Integer)
    context_version: Mapped[int | None] = mapped_column(Integer)
    decision_reason: Mapped[str | None] = mapped_column(Text)
    assumptions: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
    )
    proposal: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
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


class ChargingDatasetVersionModel(Base):
    __tablename__ = "charging_dataset_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'SUPERSEDED', 'FAILED')",
            name="ck_charging_dataset_versions_status",
        ),
        Index(
            "uq_charging_dataset_versions_active_provider",
            "provider",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    generation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_last_modified_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retrieved_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)


class ChargingLocationModel(Base):
    __tablename__ = "charging_locations"
    __table_args__ = (
        UniqueConstraint(
            "provider", "external_id", name="uq_charging_locations_provider_external"
        ),
        CheckConstraint(
            "detail_quality IN ('VERIFIED', 'PARTIAL', 'UNVERIFIED')",
            name="ck_charging_locations_detail_quality",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    dataset_version_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("charging_dataset_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_slug: Mapped[str | None] = mapped_column(String(128), nullable=True)
    access_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    charging_publish: Mapped[bool] = mapped_column(Boolean, nullable=False)
    station_status: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    location: Mapped[str] = mapped_column(
        GeographyPoint().with_variant(String(128), "sqlite"), nullable=False
    )
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_updated_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_payload: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    detail_quality: Mapped[str] = mapped_column(String(32), nullable=False, default="PARTIAL")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class ChargingEvseModel(Base):
    __tablename__ = "charging_evses"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    location_id: Mapped[int] = mapped_column(
        BIGINT_PK,
        ForeignKey("charging_locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_evse_id: Mapped[str | None] = mapped_column(String(255))
    depot_status: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str | None] = mapped_column(String(64))
    retrieved_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    source_updated_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    raw_payload: Mapped[dict | None] = mapped_column(JSON_DOCUMENT)


class ChargingConnectorModel(Base):
    __tablename__ = "charging_connectors"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    evse_id: Mapped[int] = mapped_column(
        BIGINT_PK,
        ForeignKey("charging_evses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connector_type: Mapped[str] = mapped_column(String(128), nullable=False)
    normalized_connector: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    max_electric_power_kw: Mapped[float] = mapped_column(Float, nullable=False)
    raw_payload: Mapped[dict | None] = mapped_column(JSON_DOCUMENT)


class StationExternalEvidenceModel(Base):
    __tablename__ = "station_external_evidence"
    __table_args__ = (
        CheckConstraint(
            "verification_status IN ('UNVERIFIED', 'CORROBORATED', 'REJECTED')",
            name="ck_station_external_evidence_status",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    location_id: Mapped[int | None] = mapped_column(
        BIGINT_PK,
        ForeignKey("charging_locations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    field_value_json: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    retrieved_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    source_updated_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_evidence: Mapped[dict | None] = mapped_column(JSON_DOCUMENT)


class StationGraphVersionModel(Base):
    __tablename__ = "station_graph_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('BUILDING', 'ACTIVE', 'SUPERSEDED', 'FAILED')",
            name="ck_station_graph_versions_status",
        ),
        Index(
            "uq_station_graph_versions_active_provider_profile",
            "routing_provider",
            "routing_profile",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    routing_provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    routing_profile: Mapped[str] = mapped_column(String(64), nullable=False)
    road_version: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    station_dataset_version_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("charging_dataset_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    started_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    expected_node_count: Mapped[int] = mapped_column(Integer, nullable=False)
    processed_node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edge_count: Mapped[int] = mapped_column(BIGINT_PK, nullable=False, default=0)
    last_location_id: Mapped[int | None] = mapped_column(BIGINT_PK)
    metadata_json: Mapped[dict | None] = mapped_column(JSON_DOCUMENT)
    failure_reason: Mapped[str | None] = mapped_column(Text)


class StationEdgeModel(Base):
    __tablename__ = "station_edges"
    __table_args__ = (
        UniqueConstraint(
            "graph_version_id",
            "from_location_id",
            "to_location_id",
            name="uq_station_edges_graph_directed",
        ),
    )

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    graph_version_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("station_graph_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_location_id: Mapped[int] = mapped_column(
        BIGINT_PK,
        ForeignKey("charging_locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    to_location_id: Mapped[int] = mapped_column(
        BIGINT_PK,
        ForeignKey("charging_locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    routing_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    routing_profile: Mapped[str] = mapped_column(String(64), nullable=False)
    road_version: Mapped[str] = mapped_column(String(128), nullable=False)
    distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    duration_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    geometry_polyline: Mapped[str | None] = mapped_column(Text)
    provider_source_url: Mapped[str | None] = mapped_column(Text)
    provider_retrieved_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    computed_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[object | None] = mapped_column(DateTime(timezone=True))
