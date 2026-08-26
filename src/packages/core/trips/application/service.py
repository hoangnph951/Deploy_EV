from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from src.packages.contracts.trips import (
    AssumptionSnapshot,
    InitialSocResponse,
    TripCreatedResponse,
    TripCreateRequest,
    TripDetailResponse,
    TripLocationInput,
    TripLocationResponse,
)
from src.packages.core.planning.application.orchestrator import PlanningOrchestrator, PlanningRequest
from src.packages.core.policies.application.assumptions import AssumptionSnapshotService
from src.packages.core.policies.application.service import PolicyConfigService
from src.packages.core.policies.domain.entities import DEFAULT_POLICY
from src.packages.core.trips.application.errors import (
    AppError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedActionError,
    VersionConflictError,
)
from src.packages.core.trips.domain.entities import (
    ResolvedLocationData,
    TripRecord,
    TripStatus,
)
from src.packages.core.trips.infrastructure.routing import haversine_distance_km


class TripService:
    def __init__(
        self,
        geocoder,
        repository,
        policy_service: PolicyConfigService | None = None,
        assumption_snapshot_service: AssumptionSnapshotService | None = None,
        recovery_supervisor=None,
        planning_orchestrator: PlanningOrchestrator | None = None,
    ):
        self._geocoder = geocoder
        self._repository = repository
        self._policy_service = policy_service or PolicyConfigService(override=DEFAULT_POLICY)
        self._assumption_snapshot_service = assumption_snapshot_service or AssumptionSnapshotService()
        self._recovery_supervisor = recovery_supervisor
        self._planning_orchestrator = planning_orchestrator

    def create_trip(self, request: TripCreateRequest, owner_id: str) -> TripCreatedResponse:
        try:
            vehicle_profile = self._repository.get_vehicle_profile(request.vehicle_profile_id)
        except LookupError as exc:
            raise AppError(
                code="VALIDATION_ERROR",
                status_code=400,
                message="vehicle_profile_id does not exist.",
                details={"field": "vehicle_profile_id"},
            ) from exc

        created_at = datetime.now(UTC)
        origin = self._resolve_location(request.origin, "origin")
        destination = self._resolve_location(request.destination, "destination")

        if haversine_distance_km(origin.lat, origin.lng, destination.lat, destination.lng) < 0.01:
            raise AppError(
                code="VALIDATION_ERROR",
                status_code=422,
                message="Điểm xuất phát và điểm đến phải khác nhau.",
                details={"fields": ["origin", "destination"], "reason": "SAME_ORIGIN_DESTINATION"},
            )

        assumptions = self._assumption_snapshot_service.create_snapshot(
            policy=self._policy_service.get_active_policy(),
            vehicle_profile=vehicle_profile,
            created_at=created_at,
        )

        trip = TripRecord(
            id=str(uuid4()),
            owner_id=owner_id,
            status=TripStatus.DRAFT.value,
            origin_address=origin.address,
            origin_lat=origin.lat,
            origin_lng=origin.lng,
            origin_source_type=origin.source_type,
            destination_address=destination.address,
            destination_lat=destination.lat,
            destination_lng=destination.lng,
            destination_source_type=destination.source_type,
            initial_soc_percent=request.initial_soc_percent,
            soc_source_type=request.soc_source_type,
            vehicle_profile_id=vehicle_profile.id,
            preference=request.preference,
            assumptions_json=json.dumps(assumptions.model_dump(mode="json")),
            created_at=created_at,
            updated_at=created_at,
        )
        self._repository.create_trip(trip)
        return TripCreatedResponse(
            trip_id=trip.id,
            status=trip.status,
            assumptions=assumptions,
            created_at=created_at,
        )

    def get_current_assumptions(self, vehicle_profile_id: str) -> AssumptionSnapshot:
        try:
            vehicle_profile = self._repository.get_vehicle_profile(vehicle_profile_id)
        except LookupError as exc:
            raise AppError(
                code="VALIDATION_ERROR",
                status_code=400,
                message="vehicle_profile_id does not exist.",
                details={"field": "vehicle_profile_id"},
            ) from exc

        return self._assumption_snapshot_service.create_snapshot(
            policy=self._policy_service.get_active_policy(),
            vehicle_profile=vehicle_profile,
        )

    def get_trip(self, trip_id: str, owner_id: str) -> TripDetailResponse:
        trip = self._repository.get_trip(trip_id)
        if trip is None:
            raise NotFoundError("Trip")
        if trip.owner_id != owner_id:
            raise ForbiddenError()

        assumptions_payload = json.loads(trip.assumptions_json)
        if "ambient_temperature_c" not in assumptions_payload or "vehicle_payload_kg" not in assumptions_payload:
            vehicle_profile = self._repository.get_vehicle_profile(trip.vehicle_profile_id)
            current_curve = json.loads(vehicle_profile.consumption_curve_json)
            assumptions_payload.setdefault(
                "ambient_temperature_c",
                current_curve.get("ambient_temperature_c", current_curve.get("temperature_c")),
            )
            assumptions_payload.setdefault(
                "vehicle_payload_kg",
                current_curve.get("vehicle_payload_kg", current_curve.get("payload_kg")),
            )
        assumptions_payload.setdefault("source", "POLICY_CONFIG")
        assumptions_payload.setdefault("created_at", trip.created_at.isoformat())
        assumptions = AssumptionSnapshot.model_validate(assumptions_payload)
        return TripDetailResponse(
            trip_id=trip.id,
            status=trip.status,
            owner_id=trip.owner_id,
            origin=TripLocationResponse(
                address=trip.origin_address,
                lat=trip.origin_lat,
                lng=trip.origin_lng,
                source_type=trip.origin_source_type,
            ),
            destination=TripLocationResponse(
                address=trip.destination_address,
                lat=trip.destination_lat,
                lng=trip.destination_lng,
                source_type=trip.destination_source_type,
            ),
            initial_soc=InitialSocResponse(
                value_percent=trip.initial_soc_percent,
                source_type=trip.soc_source_type,
            ),
            assumptions=assumptions,
            confirmed_plan_version=trip.confirmed_plan_version,
            latest_telemetry=None,
            active_warnings=[],
            created_at=trip.created_at,
            updated_at=trip.updated_at,
        )

    def generate_trip_plan(
        self, trip_id: str, owner_id: str, progress_callback=None, *,
        current_lat: float | None = None, current_lon: float | None = None,
        current_soc_percent: float | None = None,
    ):
        from src.packages.contracts.trips import PlanCreatedResponse, PlanProposal
        from src.packages.core.trips.domain.entities import PlanVersionRecord
        from src.packages.core.trips.infrastructure.environment import EnvironmentProviderError
        from src.packages.core.trips.infrastructure.routing import (
            RoutingProviderError,
            RoutingUnavailableError,
        )
        from src.packages.core.trips.infrastructure.station_service import StationProviderError

        trip = self._repository.get_trip(trip_id)
        if trip is None:
            raise NotFoundError("Trip")
        if trip.owner_id != owner_id:
            raise ForbiddenError()

        vehicle_profile = self._repository.get_vehicle_profile(trip.vehicle_profile_id)
        assumptions_payload = json.loads(trip.assumptions_json)
        assumptions_payload.setdefault("source", "POLICY_CONFIG")
        assumptions_payload.setdefault("created_at", trip.created_at.isoformat())
        assumptions = AssumptionSnapshot.model_validate(assumptions_payload)

        orchestrator = self._planning_orchestrator
        if orchestrator is None:
            raise RuntimeError("TripService requires a PlanningOrchestrator to generate plans.")

        # The trip application service owns authorization and persistence;
        # orchestration only computes a validated proposal or refusal.
        try:
            request = PlanningRequest(
                    trip_id=trip.id,
                    owner_id=owner_id,
                    origin_name=("Vị trí hiện tại" if current_lat is not None else trip.origin_address),
                    origin_lat=current_lat if current_lat is not None else trip.origin_lat,
                    origin_lng=current_lon if current_lon is not None else trip.origin_lng,
                    destination_name=trip.destination_address,
                    destination_lat=trip.destination_lat,
                    destination_lng=trip.destination_lng,
                    initial_soc_percent=(current_soc_percent if current_soc_percent is not None else trip.initial_soc_percent),
                    vehicle_profile=vehicle_profile,
                    assumptions=assumptions,
                )
            try:
                execution = orchestrator.plan(request, progress_callback=progress_callback)
            except TypeError:
                execution = orchestrator.plan(request)
            state = execution.state
        except RoutingProviderError as exc:
            if isinstance(exc, RoutingUnavailableError) and self._recovery_supervisor is not None:
                recovery = self._recovery_supervisor.recover_routing_endpoint(
                    trip_id=trip.id,
                    origin_name=trip.origin_address,
                    origin_lat=trip.origin_lat,
                    origin_lng=trip.origin_lng,
                    destination_name=trip.destination_address,
                    destination_lat=trip.destination_lat,
                    destination_lng=trip.destination_lng,
                    failure=exc,
                )
                if recovery is not None:
                    return recovery
            raise AppError(
                code="ROUTING_UNAVAILABLE",
                status_code=503,
                message="Không thể lấy tuyến đường thực từ Goong Directions lúc này.",
                details={"provider": "GOONG_DIRECTIONS"},
            ) from exc
        except StationProviderError as exc:
            from src.packages.core.trips.infrastructure.station_service import VinFastAccessDeniedError

            if isinstance(exc, VinFastAccessDeniedError):
                raise AppError(
                    code="VINFAST_ACCESS_DENIED",
                    status_code=503,
                    message="VinFast từ chối truy cập dữ liệu chi tiết trạm (anti-bot/WAF). Đây không phải lỗi tính khả thi hành trình.",
                    details={
                        "provider": "VINFAST_LOCATOR",
                        "provider_status": exc.provider_status,
                        "http_status": exc.http_status,
                    },
                ) from exc
            raise AppError(
                code="STATION_DATA_UNAVAILABLE",
                status_code=503,
                message="Không thể xác minh dữ liệu trạm từ VinFast hoặc nguồn web fallback lúc này.",
                details={"provider": "STATION_PROVIDER_CHAIN"},
            ) from exc
        except EnvironmentProviderError as exc:
            raise AppError(
                code="ENVIRONMENT_DATA_UNAVAILABLE",
                status_code=503,
                message="Không thể lấy dữ liệu thời tiết hoặc độ cao từ Open-Meteo lúc này.",
                details={"provider": "OPEN_METEO"},
            ) from exc

        if "no_feasible_plan" in state:
            if state.get("station_routing_rate_limited"):
                from src.packages.contracts.trips import ActionRequiredResponse, RecoveryOption

                retry_after = state.get("routing_retry_after_seconds")
                wait_text = (
                    f" khoảng {max(1, round(retry_after))} giây"
                    if isinstance(retry_after, (int, float))
                    else " một lúc"
                )
            if state.get("station_routing_budget_exhausted"):
                from src.packages.contracts.trips import ActionRequiredResponse, RecoveryOption

                return ActionRequiredResponse(
                    trip_id=trip.id,
                    summary=(
                        "Lượt tìm đã đạt ngân sách xác minh Goong trước khi chứng minh được chuỗi sạc "
                        "hoàn chỉnh. Hệ thống dừng lại để bảo vệ quota thay vì tiếp tục gửi request."
                    ),
                    failure_category="FEASIBILITY",
                    provider="GOONG_DIRECTIONS",
                    provider_status="VALIDATION_BUDGET_EXHAUSTED",
                    recovery_options=[
                        RecoveryOption(
                            code="RETRY_WITH_FRESH_ROUTING_BUDGET",
                            title="Thử lại lượt tìm mới",
                            description=(
                                "Các cạnh đã xác minh được cache; lượt tiếp theo có thể tiếp tục với ít "
                                "request Goong hơn."
                            ),
                            action="RETRY",
                        )
                    ],
                    created_at=datetime.now(UTC),
                )
                return ActionRequiredResponse(
                    trip_id=trip.id,
                    summary=(
                        "Goong đang giới hạn tần suất khi hệ thống xác minh các chặng qua trạm sạc. "
                        "Lượt tìm đã được dừng để không tiếp tục gửi request."
                    ),
                    failure_category="FEASIBILITY",
                    provider="GOONG_DIRECTIONS",
                    provider_status="RATE_LIMITED",
                    http_status=429,
                    recovery_options=[
                        RecoveryOption(
                            code="RETRY_AFTER_RATE_LIMIT",
                            title=f"Thử lại sau{wait_text}",
                            description=(
                                "Circuit breaker đang bảo vệ quota Goong. Khi hết thời gian chờ, "
                                "hãy tính lại hành trình."
                            ),
                            action="RETRY",
                        )
                    ],
                    created_at=datetime.now(UTC),
                )
            if state.get("station_provider_unavailable"):
                from src.packages.contracts.trips import ActionRequiredResponse, RecoveryOption

                return ActionRequiredResponse(
                    trip_id=trip.id,
                    summary=(
                        "Chưa thể chứng minh chuỗi sạc an toàn vì dữ liệu trạm chính thức đang không "
                        "khả dụng và tầng phục hồi không tìm được phương án đã xác minh."
                    ),
                    failure_category="STATION_DATA",
                    provider="STATION_PROVIDER_CHAIN",
                    recovery_options=[
                        RecoveryOption(
                            code="RETRY_STATION_DISCOVERY",
                            title="Thử lại dữ liệu trạm",
                            description=(
                                "Tuyến Goong đã có, nhưng dữ liệu connector/trạng thái trạm chưa đủ để "
                                "Safety Gate phê duyệt kế hoạch."
                            ),
                            action="RETRY",
                        )
                    ],
                    created_at=datetime.now(UTC),
                )
            if state.get("station_route_validation_failed"):
                from src.packages.contracts.trips import ActionRequiredResponse, RecoveryOption

                return ActionRequiredResponse(
                    trip_id=trip.id,
                    summary=(
                        "Goong đã trả tuyến chính nhưng không xác minh được các chặng qua trạm sạc. "
                        "Hệ thống chưa kết luận hành trình bất khả thi."
                    ),
                    failure_category="FEASIBILITY",
                    provider="GOONG_DIRECTIONS",
                    recovery_options=[
                        RecoveryOption(
                            code="RETRY_CHARGING_LEGS",
                            title="Tính lại các chặng qua trạm",
                            description="Thử lại khi dữ liệu Directions cho các chặng trung gian ổn định.",
                            action="RETRY",
                        )
                    ],
                    created_at=datetime.now(UTC),
                )
            # An infeasible result is not a pending plan and must not be saved
            # into plan history as though the driver could confirm it.
            return state["no_feasible_plan"]

        proposal: PlanProposal = state["plan_proposal"]
        alternatives: list[PlanProposal] = state.get("plan_alternatives", [proposal])

        conditional_codes = {
            "STATION_BUSY",
            "UNVERIFIED_STATION_DATA",
            "ENVIRONMENT_DATA_FALLBACK",
        }
        if state.get("recovery_mode") or conditional_codes.intersection(
            proposal.risk_assessment.reason_codes
        ):
            from src.packages.contracts.trips import ConditionalPlanResponse, RecoveryOption

            options = []
            if proposal.environment and proposal.environment.is_degraded:
                options.append(
                    RecoveryOption(
                        code="RETRY_LIVE_ENVIRONMENT_DATA",
                        title="Thử lại dữ liệu môi trường live",
                        description=(
                            "Kế hoạch đã áp dụng biên tiêu hao dự phòng vì Open-Meteo không khả dụng. "
                            "Hãy lập lại khi có dữ liệu live trước khi khởi hành."
                        ),
                        action="CONFIRM_CONDITIONAL",
                        verified=False,
                    )
                )
            for stop in proposal.charging_stops:
                if stop.station_status == "BUSY":
                    options.append(
                        RecoveryOption(
                            code="CONFIRM_BUSY_STATION",
                            title=f"Kiểm tra {stop.name} trước khi khởi hành",
                            description=(
                                "Nguồn VinFast đang đánh dấu trạm BUSY. Hãy xác nhận khả dụng thực tế "
                                "hoặc lập lại kế hoạch để chọn trạm khác."
                            ),
                            action="CONFIRM_CONDITIONAL",
                            verified=True,
                            source_url=stop.provenance.source_url if stop.provenance else None,
                            lat=stop.lat,
                            lng=stop.lon,
                        )
                    )
                elif stop.station_status == "UNVERIFIED":
                    options.append(
                        RecoveryOption(
                            code="VERIFY_WEB_STATION",
                            title=f"Xác minh {stop.name}",
                            description=(
                                "Trạm được OpenAI tìm từ nguồn web có dẫn chứng nhưng chưa có trạng thái "
                                "vận hành chính thức; Goong và Safety Gate đã xác minh phần tuyến/SOC."
                            ),
                            action="CONFIRM_CONDITIONAL",
                            verified=False,
                            source_url=stop.provenance.source_url if stop.provenance else None,
                            lat=stop.lat,
                            lng=stop.lon,
                        )
                    )
            return ConditionalPlanResponse(
                trip_id=trip.id,
                plan=proposal,
                alternatives=alternatives,
                recovery_options=options,
                summary=(
                    "Đã tìm được hành trình vượt Safety Gate với biên dự phòng, nhưng có dữ liệu "
                    "fallback cần xác nhận trước khi dùng."
                ),
                created_at=datetime.now(UTC),
            )

        # Calculate next version number
        existing_versions = (
            self._repository.get_plan_versions(trip_id) if hasattr(self._repository, "get_plan_versions") else []
        )
        version_num = len(existing_versions) + 1
        for alternative in alternatives:
            alternative.version = version_num

        now = datetime.now(UTC)
        if hasattr(self._repository, "save_plan_version"):
            record = PlanVersionRecord(
                id=proposal.plan_id,
                trip_id=trip.id,
                version=version_num,
                status="PENDING",
                assumptions_json=json.dumps(assumptions.model_dump(mode="json")),
                proposal_json=json.dumps(proposal.model_dump(mode="json")),
                created_at=now,
                updated_at=now,
            )
            self._repository.save_plan_version(record)

        return PlanCreatedResponse(
            trip_id=trip.id,
            plan=proposal,
            alternatives=alternatives,
            created_at=now,
        )

    def get_trip_plans(self, trip_id: str, owner_id: str):
        from src.packages.contracts.trips import PlanListResponse, PlanProposal

        trip = self._repository.get_trip(trip_id)
        if trip is None:
            raise NotFoundError("Trip")
        if trip.owner_id != owner_id:
            raise ForbiddenError()

        if not hasattr(self._repository, "get_plan_versions"):
            return PlanListResponse(trip_id=trip_id, plans=[])

        records = self._repository.get_plan_versions(trip_id)
        proposals: list[PlanProposal] = []
        for r in records:
            if r.proposal_json:
                data = json.loads(r.proposal_json)
                proposals.append(PlanProposal.model_validate(data))

        return PlanListResponse(trip_id=trip_id, plans=proposals)

    def confirm_plan(self, plan_id: str, owner_id: str, expected_version: int, ip_address: str | None = None):
        from src.packages.contracts.trips import PlanDecisionResponse, PlanProposal

        try:
            record, trip = self._repository.apply_plan_decision(
                plan_id=plan_id,
                owner_id=owner_id,
                expected_version=expected_version,
                action="CONFIRM_PLAN",
                ip_address=ip_address,
            )
        except LookupError as exc:
            raise NotFoundError("Plan") from exc
        except PermissionError as exc:
            raise UnauthorizedActionError() from exc
        except RuntimeError as exc:
            raise VersionConflictError() from exc

        proposal_data = json.loads(record.proposal_json)
        proposal_data["status"] = record.status
        return PlanDecisionResponse(
            plan=PlanProposal.model_validate(proposal_data),
            trip=self.get_trip(trip.id, owner_id),
            action="CONFIRMED",
        )

    def list_trip_history(self, owner_id: str):
        from src.packages.contracts.trips import (
            InitialSocResponse,
            PlanProposal,
            TripHistoryItem,
            TripHistoryResponse,
            TripLocationResponse,
        )

        items: list[TripHistoryItem] = []
        for trip in self._repository.list_trips_by_owner(owner_id):
            if trip.confirmed_plan_version is None:
                continue
            records = self._repository.get_plan_versions(trip.id)
            record = next(
                (
                    candidate
                    for candidate in records
                    if candidate.version == trip.confirmed_plan_version
                    and candidate.status == "CONFIRMED"
                ),
                None,
            )
            if record is None or not record.proposal_json:
                continue
            proposal_data = json.loads(record.proposal_json)
            proposal_data["status"] = record.status
            items.append(
                TripHistoryItem(
                    trip_id=trip.id,
                    status=trip.status,
                    origin=TripLocationResponse(
                        address=trip.origin_address,
                        lat=trip.origin_lat,
                        lng=trip.origin_lng,
                        source_type=trip.origin_source_type,
                    ),
                    destination=TripLocationResponse(
                        address=trip.destination_address,
                        lat=trip.destination_lat,
                        lng=trip.destination_lng,
                        source_type=trip.destination_source_type,
                    ),
                    initial_soc=InitialSocResponse(
                        value_percent=trip.initial_soc_percent,
                        source_type=trip.soc_source_type,
                    ),
                    selected_plan=PlanProposal.model_validate(proposal_data),
                    selected_at=record.updated_at,
                    created_at=trip.created_at,
                )
            )
        return TripHistoryResponse(trips=items)

    def _resolve_location(self, location: TripLocationInput, field_name: str) -> ResolvedLocationData:
        if location.lat is not None and location.lng is not None:
            return ResolvedLocationData(
                address=location.address or f"{field_name.title()} selected coordinates",
                lat=float(location.lat),
                lng=float(location.lng),
                source_type=location.source_type,
            )

        if location.address:
            candidate = self._geocoder.resolve_text(location.address, field_name)
            return ResolvedLocationData(
                address=candidate.formatted_address,
                lat=candidate.lat,
                lng=candidate.lng,
                source_type="MANUAL",
            )

        raise AppError(
            code="VALIDATION_ERROR",
            status_code=400,
            message=f"Missing {field_name} location.",
            details={"field": field_name},
        )
