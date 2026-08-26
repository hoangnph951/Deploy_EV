from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

from src.packages.contracts.trips import AssumptionSnapshot, VehicleProfileSnapshot
from src.packages.core.policies.domain.entities import PolicyConfig
from src.packages.core.trips.domain.entities import VehicleProfile


class AssumptionSnapshotService:
    """Build immutable, versioned assumptions from policy and vehicle data."""

    def __init__(
        self,
        *,
        planner_algorithm_version: str = "adaptive-beam-v1",
        energy_model_version: str = "energy-pilot-v1",
        routing_provider: str = "GOONG_DIRECTIONS",
        road_version: str = "goong-car-v1",
        station_dataset_generation_provider: Callable[[], str | None] | None = None,
    ):
        self._planner_algorithm_version = planner_algorithm_version
        self._energy_model_version = energy_model_version
        self._routing_provider = routing_provider
        self._road_version = road_version
        self._station_dataset_generation_provider = station_dataset_generation_provider

    def create_snapshot(
        self,
        *,
        policy: PolicyConfig,
        vehicle_profile: VehicleProfile,
        created_at: datetime | None = None,
    ) -> AssumptionSnapshot:
        consumption_curve = json.loads(vehicle_profile.consumption_curve_json)
        try:
            ambient_value = consumption_curve.get("ambient_temperature_c")
            if ambient_value is None:
                ambient_value = consumption_curve["temperature_c"]
            payload_value = consumption_curve.get("vehicle_payload_kg")
            if payload_value is None:
                payload_value = consumption_curve["payload_kg"]
            ambient_temperature_c = float(ambient_value)
            vehicle_payload_kg = float(payload_value)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError("Vehicle profile is missing ambient_temperature_c or vehicle_payload_kg.") from exc

        return AssumptionSnapshot(
            policy_version=policy.policy_version,
            reserve_soc_percent=policy.reserve_soc_percent,
            ambient_temperature_c=ambient_temperature_c,
            vehicle_payload_kg=vehicle_payload_kg,
            vehicle_profile_version=vehicle_profile.version,
            stale_station_hours_threshold=policy.stale_station_hours_threshold,
            route_deviation_km_threshold=policy.route_deviation_km_threshold,
            planner_algorithm_version=self._planner_algorithm_version,
            energy_model_version=self._energy_model_version,
            station_dataset_generation=(
                self._station_dataset_generation_provider()
                if self._station_dataset_generation_provider is not None
                else None
            ),
            routing_provider=self._routing_provider,
            road_version=self._road_version,
            vehicle_profile=VehicleProfileSnapshot(
                id=vehicle_profile.id,
                name=vehicle_profile.name,
                version=vehicle_profile.version,
                battery_capacity_kwh=vehicle_profile.battery_capacity_kwh,
                usable_capacity_kwh=vehicle_profile.usable_capacity_kwh,
                max_charging_power_kw=vehicle_profile.max_charging_power_kw,
                connector_type=vehicle_profile.connector_type,
                baseline_wh_per_km=float(consumption_curve["baseline_wh_per_km"]),
                reference_range_km=consumption_curve.get("reference_range_km"),
                reference_range_standard=consumption_curve.get("reference_range_standard"),
                brochure_range_km=consumption_curve.get("brochure_range_km"),
                brochure_range_standard=consumption_curve.get("brochure_range_standard"),
                motor_power_kw=consumption_curve.get("motor_power_kw"),
                max_torque_nm=consumption_curve.get("max_torque_nm"),
                drive_type=consumption_curve.get("drive_type"),
                seats=consumption_curve.get("seats"),
                curb_weight_kg=consumption_curve.get("curb_weight_kg"),
                dimensions_mm=consumption_curve.get("dimensions_mm"),
                wheelbase_mm=consumption_curve.get("wheelbase_mm"),
                ground_clearance_mm=consumption_curve.get("ground_clearance_mm"),
                wheel_size_inch=consumption_curve.get("wheel_size_inch"),
                fast_charge_10_70_min=consumption_curve.get("fast_charge_10_70_min"),
                official_source_url=consumption_curve.get("official_source"),
            ),
            source="POLICY_CONFIG",
            created_at=created_at or datetime.now(UTC),
        )
