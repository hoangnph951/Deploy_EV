"""Read-only verification of the F1 rollout schema on the configured database."""

from __future__ import annotations

import json

from sqlalchemy import create_engine, inspect, text

from src.apps.api.bootstrap.config import Settings
from src.packages.core.trips.infrastructure.database import normalize_database_url

REQUIRED_TABLES = {
    "charging_connectors",
    "charging_dataset_versions",
    "charging_evses",
    "charging_locations",
    "planning_runs",
    "station_edges",
    "station_external_evidence",
}


def main() -> int:
    engine = create_engine(normalize_database_url(Settings().database_url))
    schema = inspect(engine)
    tables = set(schema.get_table_names())
    with engine.connect() as connection:
        postgis_version = connection.execute(
            text("SELECT PostGIS_Version()")
        ).scalar_one()
        plan_counts = connection.execute(
            text(
                """
                SELECT
                    COUNT(*) AS total,
                    COUNT(proposal) AS proposal_populated,
                    COUNT(*) FILTER (
                        WHERE jsonb_exists(assumptions, :proposal_key)
                    ) AS legacy_nested
                FROM plan_versions
                """
            ),
            {"proposal_key": "proposal"},
        ).mappings().one()
        planning_run_count = connection.execute(
            text("SELECT COUNT(*) FROM planning_runs")
        ).scalar_one()

    result = {
        "missing_tables": sorted(REQUIRED_TABLES - tables),
        "postgis_version": postgis_version,
        "location_columns": [
            {
                "name": column["name"],
                "type": str(column["type"]),
                "nullable": column["nullable"],
            }
            for column in schema.get_columns("charging_locations")
            if column["name"]
            in {"active", "detail_quality", "latitude", "location", "longitude"}
        ],
        "location_indexes": [
            {
                "name": index["name"],
                "columns": index["column_names"],
                "dialect_options": {
                    key: str(value)
                    for key, value in index.get("dialect_options", {}).items()
                },
            }
            for index in schema.get_indexes("charging_locations")
        ],
        "plan_columns": [
            column["name"] for column in schema.get_columns("plan_versions")
        ],
        "plan_unique_constraints": [
            constraint["name"]
            for constraint in schema.get_unique_constraints("plan_versions")
        ],
        "plan_counts": dict(plan_counts),
        "planning_runs": planning_run_count,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["missing_tables"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
