from __future__ import annotations

import json
from datetime import UTC, datetime
from time import sleep
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from src.packages.core.trips.domain.entities import (
    PlanningRunRecord,
    PlanVersionRecord,
    TripRecord,
    VehicleProfile,
)
from src.packages.core.trips.infrastructure.database import Base, build_session_factory
from src.packages.core.trips.infrastructure.models import (
    AuditLogModel,
    PlanningRunModel,
    PlanVersionModel,
    TripModel,
    VehicleProfileModel,
)
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
                    confirmed_plan_version=trip.confirmed_plan_version,
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
                confirmed_plan_version=model.confirmed_plan_version,
            )

    def list_trips_by_owner(self, owner_id: str) -> list[TripRecord]:
        with self._session_factory() as session:
            trip_ids = session.scalars(
                select(TripModel.id)
                .where(TripModel.owner_id == owner_id)
                .order_by(TripModel.updated_at.desc())
                .limit(100)
            ).all()
        return [trip for trip_id in trip_ids if (trip := self.get_trip(trip_id)) is not None]

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
        self.save_plan_group([plan])

    def save_plan_group(self, plans: list[PlanVersionRecord]) -> int:
        """Allocate one trip version and persist all ranked proposals atomically."""
        if not plans:
            raise ValueError("At least one proposal is required.")
        trip_id = plans[0].trip_id
        if any(plan.trip_id != trip_id for plan in plans):
            raise ValueError("A plan group cannot span multiple trips.")
        ranks = [plan.rank for plan in plans]
        if len(ranks) != len(set(ranks)):
            raise ValueError("Plan ranks must be unique within a planning run.")

        last_error: IntegrityError | None = None
        for attempt in range(4):
            try:
                with self._session_factory() as session:
                    if session.bind is not None and session.bind.dialect.name == "sqlite":
                        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
                    else:
                        session.execute(
                            select(TripModel.id)
                            .where(TripModel.id == trip_id)
                            .with_for_update()
                        ).scalar_one()
                    version = int(
                        session.query(func.max(PlanVersionModel.version))
                        .filter(PlanVersionModel.trip_id == trip_id)
                        .scalar()
                        or 0
                    ) + 1
                    for plan in plans:
                        assumptions = json.loads(plan.assumptions_json)
                        # Proposal is deliberately stored in its own column.
                        assumptions.pop("proposal", None)
                        proposal = (
                            json.loads(plan.proposal_json) if plan.proposal_json else None
                        )
                        if proposal is not None:
                            proposal["version"] = version
                            proposal["status"] = plan.status
                        session.add(
                            PlanVersionModel(
                                id=plan.id,
                                trip_id=plan.trip_id,
                                version=version,
                                status=plan.status,
                                decision_reason=plan.decision_reason,
                                planning_run_id=plan.planning_run_id,
                                rank=plan.rank,
                                strategy=plan.strategy,
                                is_primary=plan.is_primary,
                                assumptions=assumptions,
                                proposal=proposal,
                                created_at=plan.created_at,
                                updated_at=plan.updated_at,
                            )
                        )
                    session.commit()
                    return version
            except IntegrityError as exc:
                last_error = exc
                sleep(0.01 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def get_plan_versions(self, trip_id: str) -> list[PlanVersionRecord]:
        with self._session_factory() as session:
            models = (
                session.query(PlanVersionModel)
                .filter(PlanVersionModel.trip_id == trip_id)
                .order_by(PlanVersionModel.version.asc(), PlanVersionModel.rank.asc())
                .all()
            )
            records: list[PlanVersionRecord] = []
            for m in models:
                assumptions_data = dict(m.assumptions) if isinstance(m.assumptions, dict) else {}
                legacy_proposal = assumptions_data.pop("proposal", None)
                proposal_data = m.proposal if m.proposal is not None else legacy_proposal
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
                        planning_run_id=m.planning_run_id,
                        rank=m.rank,
                        strategy=m.strategy,
                        is_primary=m.is_primary,
                        decision_reason=m.decision_reason,
                    )
                )
            return records

    def get_plan_version(self, plan_id: str) -> PlanVersionRecord | None:
        with self._session_factory() as session:
            model = session.get(PlanVersionModel, plan_id)
            if model is None:
                return None
            assumptions_data = dict(model.assumptions) if isinstance(model.assumptions, dict) else {}
            legacy_proposal = assumptions_data.pop("proposal", None)
            proposal_data = model.proposal if model.proposal is not None else legacy_proposal
            return PlanVersionRecord(
                id=model.id,
                trip_id=model.trip_id,
                version=model.version,
                status=model.status,
                assumptions_json=json.dumps(assumptions_data),
                proposal_json=json.dumps(proposal_data) if proposal_data else "",
                created_at=model.created_at,
                updated_at=model.updated_at,
                planning_run_id=model.planning_run_id,
                rank=model.rank,
                strategy=model.strategy,
                is_primary=model.is_primary,
                decision_reason=model.decision_reason,
            )

    def apply_plan_decision(
        self,
        *,
        plan_id: str,
        owner_id: str,
        expected_version: int,
        action: str,
        reason: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[PlanVersionRecord, TripRecord]:
        now = datetime.now(UTC)
        with self._session_factory() as session:
            plan = session.query(PlanVersionModel).filter(
                PlanVersionModel.id == plan_id
            ).with_for_update().one_or_none()
            if plan is None:
                raise LookupError("plan")
            trip = session.query(TripModel).filter(
                TripModel.id == plan.trip_id
            ).with_for_update().one_or_none()
            if trip is None:
                raise LookupError("trip")
            if trip.owner_id != owner_id:
                raise PermissionError("owner")
            if plan.version != expected_version:
                raise RuntimeError("version_conflict")
            if action == "CONFIRM_PLAN":
                newer_exists = session.query(PlanVersionModel.id).filter(
                    PlanVersionModel.trip_id == trip.id,
                    PlanVersionModel.version > expected_version,
                ).first()
                if newer_exists is not None:
                    raise RuntimeError("version_conflict")
                claimed = session.query(PlanVersionModel).filter(
                    PlanVersionModel.id == plan.id,
                    PlanVersionModel.version == expected_version,
                    PlanVersionModel.status == "PENDING",
                ).update({"status": "CONFIRMED", "updated_at": now}, synchronize_session=False)
                if claimed != 1:
                    session.rollback()
                    raise RuntimeError("version_conflict")
                session.query(PlanVersionModel).filter(
                    PlanVersionModel.trip_id == trip.id,
                    PlanVersionModel.status == "CONFIRMED",
                    PlanVersionModel.id != plan.id,
                ).update({"status": "SUPERSEDED", "updated_at": now}, synchronize_session=False)
                trip.status = "ACTIVE"
                trip.confirmed_plan_version = plan.version
            elif action == "REJECT_PLAN":
                claimed = session.query(PlanVersionModel).filter(
                    PlanVersionModel.id == plan.id,
                    PlanVersionModel.version == expected_version,
                    PlanVersionModel.status == "PENDING",
                ).update(
                    {"status": "REJECTED", "decision_reason": reason, "updated_at": now},
                    synchronize_session=False,
                )
                if claimed != 1:
                    session.rollback()
                    raise RuntimeError("version_conflict")
            else:
                raise ValueError(action)
            trip.updated_at = now
            session.add(AuditLogModel(
                id=f"audit-{uuid4().hex[:24]}", trip_id=trip.id, plan_id=plan.id,
                actor_id=owner_id, action=action, ip_address=ip_address,
                reason=reason, timestamp=now,
            ))
            session.commit()
            return self.get_plan_version(plan_id), self.get_trip(trip.id)

    def update_trip_status(self, trip_id: str, status: str) -> None:
        with self._session_factory() as session:
            trip = session.get(TripModel, trip_id)
            if trip is None:
                raise LookupError(trip_id)
            trip.status = status
            from datetime import UTC, datetime

            trip.updated_at = datetime.now(UTC)
            session.commit()

    def create_planning_run(self, run: PlanningRunRecord) -> None:
        with self._session_factory() as session:
            session.add(
                PlanningRunModel(
                    id=run.id,
                    trip_id=run.trip_id,
                    status=run.status,
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                    trace_id=run.trace_id,
                    request_snapshot=json.loads(run.request_snapshot_json),
                    result_code=run.result_code,
                    error_code=run.error_code,
                    error_detail=(
                        json.loads(run.error_detail_json)
                        if run.error_detail_json
                        else None
                    ),
                )
            )
            session.commit()

    def mark_planning_run_running(self, run_id: str, started_at) -> None:
        with self._session_factory() as session:
            run = session.get(PlanningRunModel, run_id)
            if run is None:
                raise LookupError(run_id)
            run.status = "RUNNING"
            run.started_at = started_at
            session.commit()

    def finish_planning_run(
        self,
        run_id: str,
        *,
        status: str,
        result_code: str | None,
        error_code: str | None,
        error_detail: dict | None,
        finished_at,
    ) -> None:
        with self._session_factory() as session:
            run = session.get(PlanningRunModel, run_id)
            if run is None:
                raise LookupError(run_id)
            run.status = status
            run.result_code = result_code
            run.error_code = error_code
            run.error_detail = error_detail
            run.finished_at = finished_at
            session.commit()

    def get_planning_run(self, run_id: str) -> PlanningRunRecord | None:
        with self._session_factory() as session:
            run = session.get(PlanningRunModel, run_id)
            if run is None:
                return None
            return PlanningRunRecord(
                id=run.id,
                trip_id=run.trip_id,
                status=run.status,
                request_snapshot_json=json.dumps(run.request_snapshot),
                trace_id=run.trace_id,
                started_at=run.started_at,
                finished_at=run.finished_at,
                result_code=run.result_code,
                error_code=run.error_code,
                error_detail_json=(json.dumps(run.error_detail) if run.error_detail else None),
            )


