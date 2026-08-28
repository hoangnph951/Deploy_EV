from __future__ import annotations

import json

from src.packages.contracts.monitoring import MonitoringEvent
from src.packages.core.replanning.infrastructure.models import MonitoringEventModel
from src.packages.core.trips.domain.entities import PlanVersionRecord, TripRecord, VehicleProfile
from src.packages.core.trips.infrastructure.database import Base, build_session_factory
from src.packages.core.trips.infrastructure.models import PlanVersionModel, TripModel, VehicleProfileModel
from src.packages.core.trips.infrastructure.vehicle_fixtures import load_vehicle_profile_fixtures


class SqlAlchemyTripRepository:
    def __init__(self, database_url: str):
        self._engine, self._session_factory = build_session_factory(database_url)

    def ensure_schema(self) -> None:
        Base.metadata.create_all(self._engine)
        self.seed_vehicle_profile()

    def seed_vehicle_profile(self) -> None:
        with self._session_factory() as session:
            for profile in load_vehicle_profile_fixtures():
                model = session.get(VehicleProfileModel, profile.id)
                values = {
                    "version": profile.version,
                    "name": profile.name,
                    "battery_capacity_kwh": profile.battery_capacity_kwh,
                    "usable_capacity_kwh": profile.usable_capacity_kwh,
                    "max_charging_power_kw": profile.max_charging_power_kw,
                    "connector_type": profile.connector_type,
                    "consumption_curve_json": json.loads(profile.consumption_curve_json),
                }
                if model is None:
                    session.add(
                        VehicleProfileModel(
                            id=profile.id,
                            **values,
                        )
                    )
                    continue

                for field_name, value in values.items():
                    setattr(model, field_name, value)

            session.commit()

    def create_trip(self, trip: TripRecord) -> None:
        with self._session_factory() as session:
            session.add(
                TripModel(
                    id=trip.id,
                    owner_id=trip.owner_id,
                    status=trip.status,
                    origin_address=trip.origin_address,
                    origin_lat=trip.origin_lat,
                    origin_lng=trip.origin_lng,
                    origin_source_type=trip.origin_source_type,
                    destination_address=trip.destination_address,
                    destination_lat=trip.destination_lat,
                    destination_lng=trip.destination_lng,
                    destination_source_type=trip.destination_source_type,
                    initial_soc_percent=trip.initial_soc_percent,
                    soc_source_type=trip.soc_source_type,
                    vehicle_profile_id=trip.vehicle_profile_id,
                    preference=trip.preference,
                    assumptions_json=json.loads(trip.assumptions_json),
                    created_at=trip.created_at,
                    updated_at=trip.updated_at,
                )
            )
            session.commit()

    def get_trip(self, trip_id: str) -> TripRecord | None:
        with self._session_factory() as session:
            model = session.get(TripModel, trip_id)
            if model is None:
                return None

            return TripRecord(
                id=model.id,
                owner_id=model.owner_id,
                status=model.status,
                origin_address=model.origin_address,
                origin_lat=model.origin_lat,
                origin_lng=model.origin_lng,
                origin_source_type=model.origin_source_type,
                destination_address=model.destination_address,
                destination_lat=model.destination_lat,
                destination_lng=model.destination_lng,
                destination_source_type=model.destination_source_type,
                initial_soc_percent=model.initial_soc_percent,
                soc_source_type=model.soc_source_type,
                vehicle_profile_id=model.vehicle_profile_id,
                preference=model.preference,
                assumptions_json=model.assumptions_json
                if isinstance(model.assumptions_json, str)
                else json.dumps(model.assumptions_json),
                created_at=model.created_at,
                updated_at=model.updated_at,
            )

    def get_vehicle_profile(self, requested_id: str) -> VehicleProfile:
        with self._session_factory() as session:
            model = session.get(VehicleProfileModel, requested_id)
            if model is None:
                raise LookupError(requested_id)
            return VehicleProfile(
                id=model.id,
                version=model.version,
                name=model.name,
                battery_capacity_kwh=model.battery_capacity_kwh,
                usable_capacity_kwh=model.usable_capacity_kwh,
                max_charging_power_kw=model.max_charging_power_kw,
                connector_type=model.connector_type,
                consumption_curve_json=json.dumps(model.consumption_curve_json),
            )

    def save_plan_version(self, plan: PlanVersionRecord) -> None:
        with self._session_factory() as session:
            assumptions_dict = json.loads(plan.assumptions_json)
            if plan.proposal_json:
                assumptions_dict["proposal"] = json.loads(plan.proposal_json)

            session.add(
                PlanVersionModel(
                    id=plan.id,
                    trip_id=plan.trip_id,
                    version=plan.version,
                    status=plan.status,
                    assumptions=assumptions_dict,
                    created_at=plan.created_at,
                    updated_at=plan.updated_at,
                )
            )
            session.commit()

    def get_plan_versions(self, trip_id: str) -> list[PlanVersionRecord]:
        with self._session_factory() as session:
            models = (
                session.query(PlanVersionModel)
                .filter(PlanVersionModel.trip_id == trip_id)
                .order_by(PlanVersionModel.version.asc())
                .all()
            )
            records: list[PlanVersionRecord] = []
            for m in models:
                assumptions_data = dict(m.assumptions) if isinstance(m.assumptions, dict) else {}
                proposal_data = assumptions_data.pop("proposal", None)
                records.append(
                    PlanVersionRecord(
                        id=m.id,
                        trip_id=m.trip_id,
                        version=m.version,
                        status=m.status,
                        assumptions_json=json.dumps(assumptions_data),
                        proposal_json=json.dumps(proposal_data) if proposal_data else "",
                        created_at=m.created_at,
                        updated_at=m.updated_at,
                    )
                )
            return records

    def set_plan_status(self, trip_id: str, version: int, status: str) -> bool:
        from datetime import UTC, datetime

        with self._session_factory() as session:
            now = datetime.now(UTC)
            claimed = session.query(PlanVersionModel).filter(
                PlanVersionModel.trip_id == trip_id,
                PlanVersionModel.version == version,
                PlanVersionModel.status == "PENDING",
            ).update(
                {"status": status, "updated_at": now},
                synchronize_session=False,
            )
            if claimed != 1:
                session.rollback()
                return False
            if status == "CONFIRMED":
                session.query(PlanVersionModel).filter(
                    PlanVersionModel.trip_id == trip_id,
                    PlanVersionModel.status == "CONFIRMED",
                    PlanVersionModel.version != version,
                ).update(
                    {"status": "SUPERSEDED", "updated_at": now},
                    synchronize_session=False,
                )
            session.commit()
            return True

    def save_monitoring_event(self, event: MonitoringEvent) -> None:
        with self._session_factory() as session:
            if session.get(MonitoringEventModel, event.event_id) is not None:
                return
            session.add(MonitoringEventModel(
                id=event.event_id,
                trip_id=event.trip_id,
                event_type=event.event_type,
                occurred_at=event.occurred_at,
                received_at=event.received_at,
                source_sequence=event.source_sequence,
                telemetry_snapshot_id=event.telemetry_snapshot_id,
                related_plan_version=event.related_plan_version,
                severity=event.severity,
                correlation_id=event.correlation_id,
                causation_id=event.causation_id,
                status="ACTIVE",
                evidence_json={
                    "refs": event.evidence_refs,
                    "station_ids": event.station_ids,
                    "message": event.message,
                    "payload": event.payload,
                },
            ))
            session.commit()

    def resolve_monitoring_event(self, event_id: str) -> bool:
        with self._session_factory() as session:
            updated = session.query(MonitoringEventModel).filter(
                MonitoringEventModel.id == event_id,
                MonitoringEventModel.status == "ACTIVE",
            ).update({"status": "RESOLVED"}, synchronize_session=False)
            session.commit()
            return updated == 1

    def stale_pending_plan(self, trip_id: str, version: int) -> bool:
        from datetime import UTC, datetime

        with self._session_factory() as session:
            updated = session.query(PlanVersionModel).filter(
                PlanVersionModel.trip_id == trip_id,
                PlanVersionModel.version == version,
                PlanVersionModel.status == "PENDING",
            ).update({
                "status": "STALE_BY_NEW_CONTEXT",
                "updated_at": datetime.now(UTC),
            })
            session.commit()
            return updated == 1


