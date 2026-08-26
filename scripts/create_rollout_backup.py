"""Create a secret-safe logical snapshot before the F1 rollout migration."""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import MetaData, Table, create_engine, inspect, select

from src.apps.api.bootstrap.config import Settings
from src.packages.core.trips.infrastructure.database import normalize_database_url


def _json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        return {"$base64": base64.b64encode(value).decode("ascii")}
    return value


def create_backup(output_dir: Path) -> tuple[Path, str, dict[str, int]]:
    database_url = normalize_database_url(Settings().database_url)
    engine = create_engine(database_url)
    timestamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"f1-pre-migration-{timestamp}.json.gz"
    counts: dict[str, int] = {}

    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        transaction = connection.begin()
        try:
            schema = inspect(connection)
            payload: dict = {
                "created_at": datetime.now().astimezone().isoformat(),
                "dialect": engine.dialect.name,
                "tables": {},
            }
            for table_name in sorted(schema.get_table_names()):
                table = Table(table_name, MetaData(), autoload_with=connection)
                rows = [
                    {
                        key: _json_value(value)
                        for key, value in row._mapping.items()
                    }
                    for row in connection.execute(select(table))
                ]
                counts[table_name] = len(rows)
                payload["tables"][table_name] = {
                    "columns": [
                        {
                            "name": column["name"],
                            "type": str(column["type"]),
                            "nullable": column["nullable"],
                            "default": str(column.get("default")),
                        }
                        for column in schema.get_columns(table_name)
                    ],
                    "primary_key": schema.get_pk_constraint(table_name),
                    "foreign_keys": schema.get_foreign_keys(table_name),
                    "unique_constraints": schema.get_unique_constraints(table_name),
                    "indexes": schema.get_indexes(table_name),
                    "rows": rows,
                }
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                default=_json_value,
                separators=(",", ":"),
            ).encode("utf-8")
            with gzip.open(output_path, "wb", compresslevel=9) as backup_file:
                backup_file.write(encoded)
        finally:
            transaction.rollback()

    checksum = hashlib.sha256(output_path.read_bytes()).hexdigest()
    return output_path, checksum, counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/rollout_backups"),
    )
    args = parser.parse_args()
    path, checksum, counts = create_backup(args.output_dir)
    print(f"backup_path={path}")
    print(f"sha256={checksum}")
    print("row_counts=" + json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
