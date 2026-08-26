from __future__ import annotations

import heapq
import json
import math
from dataclasses import dataclass, field
from itertools import count

from src.packages.contracts.trips import (
    AssumptionSnapshot,
    ChargingStopProposal,
    EnvironmentSnapshot,
    SocPoint,
)
from src.packages.core.trips.domain.entities import VehicleProfile
from src.packages.core.trips.infrastructure.station_service import CandidateStation


@dataclass(frozen=True)
class EnergyLegCalculation:
    from_name: str
    to_name: str
    distance_km: float
    energy_consumed_kwh: float
    start_soc_percent: float
    arrival_soc_percent: float


@dataclass(frozen=True)
class EnergySimulationResult:
    legs: list[EnergyLegCalculation]
    charging_stops: list[ChargingStopProposal]
    final_arrival_soc_percent: float
    total_energy_kwh: float
    total_charge_time_min: float
    min_soc_encountered: float
    effective_consumption_wh_per_km: float = 0.0
    soc_points: list[SocPoint] = field(default_factory=list)
    unreachable_next_station: bool = False


@dataclass(frozen=True)
class StationChainCandidate:
    stations: list[CandidateStation]
    estimated_total_minutes: float


class EnergyTool:
    """Deterministic SOC estimation using vehicle data and live conditions."""

    @staticmethod
    def calculate_consumption_rate(
        baseline_wh_per_km: float,
        ambient_temp_c: float,
        payload_kg: float,
        *,
        precipitation_mm: float = 0.0,
        wind_speed_kmh: float = 0.0,
        elevation_gain_m: float = 0.0,
        elevation_loss_m: float = 0.0,
        total_distance_km: float = 1.0,
        curb_weight_kg: float = 2000.0,
    ) -> float:
        temp_delta = abs(ambient_temp_c - 22.0)
        temperature_factor = 1.0 + min(0.20, temp_delta * 0.004)
        payload_factor = max(0.9, 1.0 + ((payload_kg - 150.0) / 100.0) * 0.02)
        weather_factor = (
            1.0
            + min(0.08, precipitation_mm * 0.01)
            + min(0.12, wind_speed_kmh * 0.003)
        )

        vehicle_mass_kg = max(500.0, curb_weight_kg + payload_kg)
        uphill_wh = vehicle_mass_kg * 9.80665 * elevation_gain_m / (3600.0 * 0.85)
        recovered_wh = vehicle_mass_kg * 9.80665 * elevation_loss_m / 3600.0 * 0.60
        elevation_wh_per_km = max(0.0, uphill_wh - recovered_wh) / max(
            1.0, total_distance_km
        )
        return (
            baseline_wh_per_km * temperature_factor * payload_factor * weather_factor
            + elevation_wh_per_km
        )

    def effective_consumption_rate(
        self,
        total_distance_km: float,
        vehicle_profile: VehicleProfile,
        assumptions: AssumptionSnapshot,
        environment: EnvironmentSnapshot,
    ) -> float:
        curve = json.loads(vehicle_profile.consumption_curve_json)
        calculated_rate = self.calculate_consumption_rate(
            float(curve["baseline_wh_per_km"]),
            environment.temperature_c,
            assumptions.vehicle_payload_kg,
            precipitation_mm=environment.precipitation_mm,
            wind_speed_kmh=environment.wind_speed_kmh,
            elevation_gain_m=environment.elevation_gain_m,
            elevation_loss_m=environment.elevation_loss_m,
            total_distance_km=total_distance_km,
            curb_weight_kg=float(curve.get("curb_weight_kg", 2000.0)),
        )
        return calculated_rate * (1.0 + environment.consumption_margin_percent / 100.0)

    def recommended_search_stop_limit(
        self,
        *,
        total_distance_km: float,
        initial_soc_percent: float,
        vehicle_profile: VehicleProfile,
        assumptions: AssumptionSnapshot,
        environment: EnvironmentSnapshot,
        candidate_station_count: int,
        recovery_margin_stops: int = 3,
    ) -> int:
        """Size the chain search from the vehicle's safe range, not a fixed cap."""
        if candidate_station_count <= 0:
            return 0

        usable_kwh = max(10.0, vehicle_profile.usable_capacity_kwh)
        effective_wh_km = self.effective_consumption_rate(
            total_distance_km, vehicle_profile, assumptions, environment
        )
        reserve_soc = assumptions.reserve_soc_percent
        initial_range_km = (
            usable_kwh
            * max(0.0, initial_soc_percent - reserve_soc)
            / 100.0
            * 1000.0
            / effective_wh_km
        )
        full_charge_range_km = (
            usable_kwh
            * max(0.0, 100.0 - reserve_soc)
            / 100.0
            * 1000.0
            / effective_wh_km
        )
        if full_charge_range_km <= 0.0:
            return candidate_station_count

        remaining_km = max(0.0, total_distance_km - initial_range_km)
        minimum_stops = math.ceil(remaining_km / full_charge_range_km)
        adaptive_limit = minimum_stops + max(0, recovery_margin_stops)
        return min(candidate_station_count, max(1, adaptive_limit))

    def find_station_chains(
        self,
        *,
        total_distance_km: float,
        initial_soc_percent: float,
        vehicle_profile: VehicleProfile,
        assumptions: AssumptionSnapshot,
        candidate_stations: list[CandidateStation],
        environment: EnvironmentSnapshot,
        max_results: int = 8,
        max_stops: int | None = None,
        max_state_expansions: int = 50_000,
    ) -> list[StationChainCandidate]:
        """Find safe station chains on the route corridor.

        Stations projected at progress zero are intentionally retained. They
        represent a charger close to, or behind, the origin and may require a
        short backtrack. The final candidate routes are still rebuilt through
        the routing provider before a proposal can be accepted.
        """
        usable_kwh = max(10.0, vehicle_profile.usable_capacity_kwh)
        effective_wh_km = self.effective_consumption_rate(
            total_distance_km, vehicle_profile, assumptions, environment
        )
        reserve_soc = assumptions.reserve_soc_percent
        stations = sorted(
            [
                station
                for station in candidate_stations
                if 0.0 <= station.distance_from_origin_km < total_distance_km
            ],
            key=lambda station: (
                station.distance_from_origin_km,
                station.detour_distance_km,
                -station.max_power_kw,
            ),
        )
        stop_limit = len(stations) if max_stops is None else max(0, max_stops)

        sequence = count()
        # cost, tie-breaker, last station index, SOC, progress, egress,
        # path indexes, accumulated drive distance
        queue: list[tuple[float, int, int, float, float, float, tuple[int, ...], float]] = [
            (0.0, next(sequence), -1, float(initial_soc_percent), 0.0, 0.0, (), 0.0)
        ]
        labels: dict[int, list[float]] = {}
        solutions: list[StationChainCandidate] = []
        seen_paths: set[tuple[str, ...]] = set()
        expanded_states = 0

        while (
            queue
            and len(solutions) < max_results
            and expanded_states < max(1, max_state_expansions)
        ):
            expanded_states += 1
            cost, _, last_index, current_soc, progress, egress_km, path, driven_km = heapq.heappop(queue)
            destination_distance = egress_km + max(0.0, total_distance_km - progress)
            destination_soc = current_soc - (
                destination_distance * effective_wh_km / 1000.0 / usable_kwh * 100.0
            )
            if destination_soc >= reserve_soc:
                station_path = [stations[index] for index in path]
                identity = tuple(station.station_id for station in station_path)
                if identity not in seen_paths:
                    seen_paths.add(identity)
                    solutions.append(
                        StationChainCandidate(
                            stations=station_path,
                            estimated_total_minutes=round(
                                cost + destination_distance / 50.0 * 60.0, 1
                            ),
                        )
                    )
                continue

            if len(path) >= stop_limit:
                continue

            for index, station in enumerate(stations):
                if index in path:
                    continue
                station_progress = station.distance_from_origin_km
                if path and station_progress <= progress + 0.05:
                    continue
                if not path and station_progress < progress:
                    continue

                ingress_km = max(0.0, station.detour_distance_km / 2.0)
                distance_to_station = (
                    egress_km + max(0.0, station_progress - progress) + ingress_km
                )
                arrival_soc = current_soc - (
                    distance_to_station * effective_wh_km / 1000.0 / usable_kwh * 100.0
                )
                if arrival_soc < reserve_soc:
                    continue

                # Search assumes a full charge for maximum reachability. Once a
                # chain is chosen, simulate_fixed_itinerary reduces each target
                # to the minimum safe value, with 80% as the normal fast-charge
                # target and 100% only when the following leg requires it.
                departure_soc = 100.0
                energy_added_kwh = max(0.0, departure_soc - arrival_soc) / 100.0 * usable_kwh
                effective_power_kw = max(
                    1.0,
                    min(station.max_power_kw, vehicle_profile.max_charging_power_kw) * 0.85,
                )
                charge_minutes = energy_added_kwh / effective_power_kw * 60.0
                drive_minutes = distance_to_station / 50.0 * 60.0
                next_cost = cost + drive_minutes + charge_minutes

                node_labels = labels.setdefault(index, [])
                if len(node_labels) >= 3 and next_cost >= max(node_labels):
                    continue
                node_labels.append(next_cost)
                node_labels.sort()
                del node_labels[3:]
                heapq.heappush(
                    queue,
                    (
                        next_cost,
                        next(sequence),
                        index,
                        departure_soc,
                        station_progress,
                        ingress_km,
                        (*path, index),
                        driven_km + distance_to_station,
                    ),
                )

        return solutions

    def simulate_fixed_itinerary(
        self,
        *,
        leg_distances_km: list[float],
        initial_soc_percent: float,
        vehicle_profile: VehicleProfile,
        assumptions: AssumptionSnapshot,
        stations: list[CandidateStation],
        environment: EnvironmentSnapshot,
        charge_buffer_percent: float = 3.0,
    ) -> EnergySimulationResult:
        """Simulate an exact routed itinerary (origin, stops, destination)."""
        if len(leg_distances_km) != len(stations) + 1:
            raise ValueError("leg_distances_km must contain one leg per stop plus destination.")

        total_distance_km = sum(leg_distances_km)
        usable_kwh = max(10.0, vehicle_profile.usable_capacity_kwh)
        effective_wh_km = self.effective_consumption_rate(
            total_distance_km, vehicle_profile, assumptions, environment
        )
        reserve_soc = assumptions.reserve_soc_percent
        current_soc = float(initial_soc_percent)
        cumulative_distance = 0.0
        total_energy_kwh = 0.0
        total_charge_time_min = 0.0
        min_soc = current_soc
        unreachable = False
        legs: list[EnergyLegCalculation] = []
        charging_stops: list[ChargingStopProposal] = []
        soc_points = [
            SocPoint(distance_km=0.0, soc_percent=round(current_soc, 1), kind="ORIGIN", label="Xuất phát")
        ]
        from_name = "Origin"

        for index, station in enumerate(stations):
            distance_km = max(0.0, leg_distances_km[index])
            energy_kwh = distance_km * effective_wh_km / 1000.0
            arrival_soc = current_soc - energy_kwh / usable_kwh * 100.0
            cumulative_distance += distance_km
            total_energy_kwh += energy_kwh
            min_soc = min(min_soc, arrival_soc)
            if arrival_soc < reserve_soc:
                unreachable = True
            legs.append(
                EnergyLegCalculation(
                    from_name=from_name,
                    to_name=station.name,
                    distance_km=round(distance_km, 2),
                    energy_consumed_kwh=round(energy_kwh, 2),
                    start_soc_percent=round(current_soc, 1),
                    arrival_soc_percent=round(arrival_soc, 1),
                )
            )
            soc_points.append(
                SocPoint(
                    distance_km=round(cumulative_distance, 2),
                    soc_percent=round(arrival_soc, 1),
                    kind="ARRIVAL",
                    label=f"Đến {station.name}",
                )
            )

            next_leg_km = max(0.0, leg_distances_km[index + 1])
            required_departure_soc = (
                next_leg_km * effective_wh_km / 1000.0 / usable_kwh * 100.0
                + reserve_soc
                + charge_buffer_percent
            )
            departure_soc = min(100.0, max(arrival_soc, 80.0, required_departure_soc))
            energy_added = max(0.0, departure_soc - arrival_soc) / 100.0 * usable_kwh
            effective_power_kw = max(
                1.0,
                min(station.max_power_kw, vehicle_profile.max_charging_power_kw) * 0.85,
            )
            charge_time_min = energy_added / effective_power_kw * 60.0
            total_charge_time_min += charge_time_min
            charging_stops.append(
                ChargingStopProposal(
                    station_id=station.station_id,
                    name=station.name,
                    lat=station.lat,
                    lon=station.lon,
                    address=station.address,
                    arrival_soc_percent=round(arrival_soc, 1),
                    departure_soc_percent=round(departure_soc, 1),
                    charge_duration_min=round(charge_time_min, 1),
                    energy_added_kwh=round(energy_added, 2),
                    max_power_kw=station.max_power_kw,
                    connector_type=station.connector_types[0],
                    connector_standard=station.connector_standard,
                    port_count=station.port_count,
                    station_status=station.station_status,
                    opening_24_7=station.opening_24_7,
                    access_type=station.access_type,
                    parking_fee=station.parking_fee,
                    station_updated_at=station.station_updated_at,
                    detour_distance_km=station.detour_distance_km,
                    detour_duration_min=station.detour_duration_min,
                    freshness=station.freshness,
                    distance_from_origin_km=round(cumulative_distance, 2),
                    provenance=station.provenance,
                )
            )
            soc_points.append(
                SocPoint(
                    distance_km=round(cumulative_distance, 2),
                    soc_percent=round(departure_soc, 1),
                    kind="DEPARTURE",
                    label=f"Rời {station.name}",
                )
            )
            current_soc = departure_soc
            from_name = station.name

        final_distance = max(0.0, leg_distances_km[-1])
        final_energy = final_distance * effective_wh_km / 1000.0
        final_arrival_soc = current_soc - final_energy / usable_kwh * 100.0
        cumulative_distance += final_distance
        total_energy_kwh += final_energy
        min_soc = min(min_soc, final_arrival_soc)
        if final_arrival_soc < reserve_soc:
            unreachable = True
        legs.append(
            EnergyLegCalculation(
                from_name=from_name,
                to_name="Destination",
                distance_km=round(final_distance, 2),
                energy_consumed_kwh=round(final_energy, 2),
                start_soc_percent=round(current_soc, 1),
                arrival_soc_percent=round(final_arrival_soc, 1),
            )
        )
        soc_points.append(
            SocPoint(
                distance_km=round(cumulative_distance, 2),
                soc_percent=round(final_arrival_soc, 1),
                kind="DESTINATION",
                label="Điểm đến",
            )
        )
        return EnergySimulationResult(
            legs=legs,
            charging_stops=charging_stops,
            final_arrival_soc_percent=round(final_arrival_soc, 1),
            total_energy_kwh=round(total_energy_kwh, 2),
            total_charge_time_min=round(total_charge_time_min, 1),
            min_soc_encountered=round(min_soc, 1),
            effective_consumption_wh_per_km=round(effective_wh_km, 1),
            soc_points=soc_points,
            unreachable_next_station=unreachable,
        )

    def simulate_trip_soc(
        self,
        total_distance_km: float,
        initial_soc_percent: float,
        vehicle_profile: VehicleProfile,
        assumptions: AssumptionSnapshot,
        candidate_stations: list[CandidateStation],
        environment: EnvironmentSnapshot,
    ) -> EnergySimulationResult:
        chains = self.find_station_chains(
            total_distance_km=total_distance_km,
            initial_soc_percent=initial_soc_percent,
            vehicle_profile=vehicle_profile,
            assumptions=assumptions,
            candidate_stations=candidate_stations,
            environment=environment,
            max_results=1,
        )
        if chains:
            stations = chains[0].stations
            leg_distances: list[float] = []
            progress = 0.0
            egress = 0.0
            for station in stations:
                ingress = max(0.0, station.detour_distance_km / 2.0)
                leg_distances.append(
                    egress + max(0.0, station.distance_from_origin_km - progress) + ingress
                )
                progress = station.distance_from_origin_km
                egress = ingress
            leg_distances.append(egress + max(0.0, total_distance_km - progress))
            return self.simulate_fixed_itinerary(
                leg_distances_km=leg_distances,
                initial_soc_percent=initial_soc_percent,
                vehicle_profile=vehicle_profile,
                assumptions=assumptions,
                stations=stations,
                environment=environment,
            )

        return self.simulate_fixed_itinerary(
            leg_distances_km=[total_distance_km],
            initial_soc_percent=initial_soc_percent,
            vehicle_profile=vehicle_profile,
            assumptions=assumptions,
            stations=[],
            environment=environment,
        )
