from __future__ import annotations

import sqlite3
from pathlib import Path

from src.packages.core.trips.domain.entities import PlanVersionRecord, TripRecord, VehicleProfile


class SqliteTripRepository:
    def __init__(self, database_url: str):
        self._db_path = self._parse_sqlite_path(database_url)
        self._ensure_schema()

    def create_trip(self, trip: TripRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO trips (
                    id, owner_id, status,
                    origin_name, origin_lat, origin_lon,
                    destination_name, destination_lat, destination_lon,
                    initial_soc_percent, vehicle_profile_id, assumptions_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trip.id,
                    trip.owner_id,
                    trip.status,
                    trip.origin_name,
                    trip.origin_lat,
                    trip.origin_lon,
                    trip.destination_name,
                    trip.destination_lat,
                    trip.destination_lon,
                    trip.initial_soc_percent,
                    trip.vehicle_profile_id,
                    trip.assumptions_json,
                    trip.created_at.isoformat(),
                    trip.updated_at.isoformat(),
                ),
            )

    def get_trip(self, trip_id: str) -> TripRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id, owner_id, status,
                    origin_name, origin_lat, origin_lon,
                    destination_name, destination_lat, destination_lon,
                    initial_soc_percent, vehicle_profile_id, assumptions_json,
                    created_at, updated_at
                FROM trips
                WHERE id = ?
                """,
                (trip_id,),
            ).fetchone()

        if row is None:
            return None

        return TripRecord(
            id=row["id"],
            owner_id=row["owner_id"],
            status=row["status"],
            origin_name=row["origin_name"],
            origin_lat=row["origin_lat"],
            origin_lon=row["origin_lon"],
            destination_name=row["destination_name"],
            destination_lat=row["destination_lat"],
            destination_lon=row["destination_lon"],
            initial_soc_percent=row["initial_soc_percent"],
            vehicle_profile_id=row["vehicle_profile_id"],
            assumptions_json=row["assumptions_json"],
            created_at=self._from_iso(row["created_at"]),
            updated_at=self._from_iso(row["updated_at"]),
        )

    def get_vehicle_profile(self, requested_id: str | None) -> VehicleProfile:
        profile_id = requested_id or "xe_x_v1"

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, version, name
                FROM vehicle_profiles
                WHERE id = ?
                """,
                (profile_id,),
            ).fetchone()

        if row is None:
            raise ValueError(f"Unknown vehicle_profile_id: {profile_id}")

        return VehicleProfile(id=row["id"], version=row["version"], name=row["name"])

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trips (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    origin_name TEXT NOT NULL,
                    origin_lat REAL NOT NULL,
                    origin_lon REAL NOT NULL,
                    destination_name TEXT NOT NULL,
                    destination_lat REAL NOT NULL,
                    destination_lon REAL NOT NULL,
                    initial_soc_percent REAL NOT NULL,
                    vehicle_profile_id TEXT NOT NULL,
                    assumptions_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS vehicle_profiles (
                    id TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    name TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS plan_versions (
                    id TEXT PRIMARY KEY,
                    trip_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    assumptions TEXT NOT NULL,
                    proposal_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO vehicle_profiles (id, version, name)
                VALUES ('xe_x_v1', 'xe_x_v1.0', 'Xe X v1')
                """
            )

    def save_plan_version(self, plan: PlanVersionRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO plan_versions (
                    id, trip_id, version, status, assumptions, proposal_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.id,
                    plan.trip_id,
                    plan.version,
                    plan.status,
                    plan.assumptions_json,
                    plan.proposal_json,
                    plan.created_at.isoformat(),
                    plan.updated_at.isoformat(),
                ),
            )
            connection.commit()

    def get_plan_versions(self, trip_id: str) -> list[PlanVersionRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, trip_id, version, status, assumptions, proposal_json, created_at, updated_at
                FROM plan_versions
                WHERE trip_id = ?
                ORDER BY version ASC
                """,
                (trip_id,),
            ).fetchall()

            return [
                PlanVersionRecord(
                    id=row["id"],
                    trip_id=row["trip_id"],
                    version=row["version"],
                    status=row["status"],
                    assumptions_json=row["assumptions"],
                    proposal_json=row["proposal_json"] or "",
                    created_at=self._from_iso(row["created_at"]),
                    updated_at=self._from_iso(row["updated_at"]),
                )
                for row in rows
            ]


    def _parse_sqlite_path(self, database_url: str) -> Path:
        prefix = "sqlite:///"
        if not database_url.startswith(prefix):
            raise ValueError("Only sqlite:/// URLs are supported in the current F1-US1 slice.")
        return Path(database_url[len(prefix) :]).resolve()

    def _from_iso(self, value: str):
        from datetime import datetime

        return datetime.fromisoformat(value)
