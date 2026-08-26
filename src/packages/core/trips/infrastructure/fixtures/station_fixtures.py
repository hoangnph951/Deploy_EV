from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_FIXTURES_PATH = Path(__file__).resolve().parent / "station_fixture.json"


@dataclass(frozen=True)
class StationSnapshotFixture:
    id: str
    name: str
    lat: float
    lon: float
    address: str
    connector_types: list[str]
    max_power_kw: float
    source: str
    snapshot_timestamp: str
    status: str


def load_station_fixtures() -> list[StationSnapshotFixture]:
    if not _FIXTURES_PATH.exists():
        return []
    with open(_FIXTURES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return [
        StationSnapshotFixture(
            id=item["id"],
            name=item["name"],
            lat=float(item["lat"]),
            lon=float(item["lon"]),
            address=item.get("address", ""),
            connector_types=item.get("connector_types", ["CCS2"]),
            max_power_kw=float(item.get("max_power_kw", 150.0)),
            source=item.get("source", "CACHED_SNAPSHOT"),
            snapshot_timestamp=item.get("snapshot_timestamp", "2026-08-08T00:00:00Z"),
            status=item.get("status", "OPERATIONAL"),
        )
        for item in data
    ]
