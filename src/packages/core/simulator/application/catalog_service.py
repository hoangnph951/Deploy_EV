from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from src.packages.contracts.simulator import SimulationCase, SimulationCatalogResponse

PROFILES = (
    "NORMAL",
    "ROUTE_DEVIATION",
    "SOC_UNDERPERFORMANCE",
    "STATION_UNAVAILABLE",
    "STALE_TELEMETRY",
    "NO_FEASIBLE_ALTERNATIVE",
)


@dataclass(frozen=True)
class BaseSimulationSnapshot:
    base_case_id: str
    log_file: str
    run_id: str
    origin_name: str
    origin_lat: float
    origin_lng: float
    destination_name: str
    destination_lat: float
    destination_lng: float
    initial_soc_percent: float
    provider: str
    route: dict[str, Any]
    energy: dict[str, Any]
    verdict: dict[str, Any]
    input_state: dict[str, Any]

    @property
    def charging_stops(self) -> list[dict[str, Any]]:
        return list(self.energy.get("charging_stops") or [])

    @property
    def semantic_key(self) -> tuple[str, str, float]:
        """Identify one business trip even when F1 produced retry/branch logs."""
        return (
            " ".join(self.origin_name.casefold().split()),
            " ".join(self.destination_name.casefold().split()),
            round(self.initial_soc_percent, 1),
        )


class SimulationCatalogService:
    def __init__(self, log_directory: Path, *, max_base_logs: int = 15):
        self._log_directory = log_directory
        self._max_base_logs = max_base_logs
        self._snapshots: dict[str, BaseSimulationSnapshot] = {}
        self._cases: dict[str, SimulationCase] = {}
        self.reload()

    def reload(self) -> None:
        snapshots: list[BaseSimulationSnapshot] = []
        seen_business_cases: set[tuple[str, str, float]] = set()
        if self._log_directory.exists():
            files = sorted(
                self._log_directory.glob("*.jsonl"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            for path in files:
                snapshot = self._read_snapshot(path)
                if snapshot is not None and snapshot.semantic_key not in seen_business_cases:
                    snapshots.append(snapshot)
                    seen_business_cases.add(snapshot.semantic_key)
                if len(snapshots) >= self._max_base_logs:
                    break

        self._snapshots = {item.base_case_id: item for item in snapshots}
        self._cases = {}
        for snapshot in snapshots:
            for profile in PROFILES:
                ready = True
                reason = None
                if profile in {"STATION_UNAVAILABLE", "NO_FEASIBLE_ALTERNATIVE"} and not snapshot.charging_stops:
                    ready = False
                    reason = "F1 log không có charging stop để mô phỏng station disruption."
                case_id = f"{snapshot.base_case_id}__{profile}"
                self._cases[case_id] = SimulationCase(
                    case_id=case_id,
                    base_case_id=snapshot.base_case_id,
                    log_file=snapshot.log_file,
                    run_id=snapshot.run_id,
                    origin_name=snapshot.origin_name,
                    destination_name=snapshot.destination_name,
                    initial_soc_percent=snapshot.initial_soc_percent,
                    profile=profile,
                    provider=snapshot.provider,
                    distance_km=float(snapshot.route.get("distance_km") or 0),
                    charging_stop_count=len(snapshot.charging_stops),
                    readiness="READY" if ready else "NOT_APPLICABLE",
                    readiness_reason=reason,
                )

    def catalog(self) -> SimulationCatalogResponse:
        cases = sorted(
            self._cases.values(),
            key=lambda item: (item.origin_name, item.destination_name, item.initial_soc_percent, item.profile),
        )
        return SimulationCatalogResponse(
            available_base_log_count=len(self._snapshots),
            generated_case_count=len(cases),
            ready_case_count=sum(item.readiness == "READY" for item in cases),
            cases=cases,
        )

    def get_case(self, case_id: str) -> SimulationCase:
        try:
            return self._cases[case_id]
        except KeyError as exc:
            raise KeyError("Simulation case not found.") from exc

    def get_snapshot_for_case(self, case_id: str) -> BaseSimulationSnapshot:
        case = self.get_case(case_id)
        return self._snapshots[case.base_case_id]

    @staticmethod
    def _read_snapshot(path: Path) -> BaseSimulationSnapshot | None:
        start: dict[str, Any] | None = None
        finish: dict[str, Any] | None = None
        try:
            with path.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    try:
                        item = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue
                    if item.get("event") == "run_started":
                        start = item
                    elif item.get("event") == "run_finished":
                        finish = item
        except OSError:
            return None
        if not start or not finish:
            return None
        state = finish.get("output_state") or {}
        feasible = next(
            (
                item
                for item in state.get("validated") or []
                if (item.get("verdict") or {}).get("is_feasible")
                and len((item.get("route") or {}).get("polyline") or []) >= 2
            ),
            None,
        )
        if feasible is None:
            return None

        input_state = start.get("input_state") or {}
        origin_payload = input_state.get("origin") or {}
        if (
            (input_state.get("metadata") or {}).get("trigger") == "F4_REPLAN"
            or str(input_state.get("trip_id") or "").startswith("simulation:")
            or input_state.get("origin_name") == "Vị trí hiện tại của xe"
            or origin_payload.get("name") == "Vị trí hiện tại của xe"
        ):
            return None
        origin = origin_payload
        destination = input_state.get("destination") or {}
        origin_name = input_state.get("origin_name") or origin.get("name") or "Origin"
        destination_name = input_state.get("destination_name") or destination.get("name") or "Destination"
        origin_lat = input_state.get("origin_lat", origin.get("lat"))
        origin_lng = input_state.get("origin_lng", origin.get("lng"))
        destination_lat = input_state.get("destination_lat", destination.get("lat"))
        destination_lng = input_state.get("destination_lng", destination.get("lng"))
        route = feasible.get("route") or {}
        polyline = route.get("polyline") or []
        origin_lat = float(origin_lat if origin_lat is not None else polyline[0][0])
        origin_lng = float(origin_lng if origin_lng is not None else polyline[0][1])
        destination_lat = float(destination_lat if destination_lat is not None else polyline[-1][0])
        destination_lng = float(destination_lng if destination_lng is not None else polyline[-1][1])
        semantic_identity = "|".join(
            (
                " ".join(str(origin_name).casefold().split()),
                " ".join(str(destination_name).casefold().split()),
                str(round(float(input_state.get("initial_soc_percent") or 0), 1)),
            )
        )
        return BaseSimulationSnapshot(
            base_case_id=f"f1-{uuid5(NAMESPACE_URL, semantic_identity).hex[:16]}",
            log_file=path.name,
            run_id=str(start.get("run_id") or path.stem),
            origin_name=str(origin_name),
            origin_lat=origin_lat,
            origin_lng=origin_lng,
            destination_name=str(destination_name),
            destination_lat=destination_lat,
            destination_lng=destination_lng,
            initial_soc_percent=float(input_state.get("initial_soc_percent") or 0),
            provider=str(route.get("provider") or "UNKNOWN"),
            route=route,
            energy=feasible.get("energy") or {},
            verdict=feasible.get("verdict") or {},
            input_state=input_state,
        )
