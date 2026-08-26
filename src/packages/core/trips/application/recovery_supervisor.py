from __future__ import annotations

from datetime import UTC, datetime

from src.packages.contracts.trips import ActionRequiredResponse, RecoveryOption
from src.packages.core.trips.application.errors import AppError
from src.packages.core.trips.infrastructure.openai_recovery import RecoveryAdvisor
from src.packages.core.trips.infrastructure.routing import RoutingProvider, RoutingUnavailableError


class RecoverySupervisor:
    """Classify deterministic failures and validate any AI-proposed recovery."""

    def __init__(self, *, advisor: RecoveryAdvisor, geocoder, routing_provider: RoutingProvider):
        self._advisor = advisor
        self._geocoder = geocoder
        self._routing_provider = routing_provider

    def recover_routing_endpoint(
        self,
        *,
        trip_id: str,
        origin_name: str,
        origin_lat: float,
        origin_lng: float,
        destination_name: str,
        destination_lat: float,
        destination_lng: float,
        failure: RoutingUnavailableError,
    ) -> ActionRequiredResponse | None:
        if failure.retryable and failure.provider_status != "NOT_FOUND":
            return None

        options: list[RecoveryOption] = []
        try:
            suggestions = self._advisor.suggest_endpoint_access(
                origin_name=origin_name,
                origin_lat=origin_lat,
                origin_lng=origin_lng,
                destination_name=destination_name,
                destination_lat=destination_lat,
                destination_lng=destination_lng,
                provider_status=failure.provider_status,
            )
        except Exception:
            suggestions = []
        for suggestion in suggestions:
            try:
                location = self._geocoder.resolve_text(
                    f"{suggestion.name}, {suggestion.address}",
                    "recovery_destination",
                )
                self._routing_provider.get_route(
                    origin_lat,
                    origin_lng,
                    location.lat,
                    location.lng,
                )
            except (AppError, LookupError, RoutingUnavailableError):
                continue
            options.append(
                RecoveryOption(
                    code="VERIFIED_ALTERNATE_ACCESS_POINT",
                    title=suggestion.name,
                    description=(
                        f"Goong đã xác minh có tuyến ô tô tới điểm tiếp cận này. {suggestion.evidence}"
                    ),
                    action="CHANGE_ENDPOINT",
                    verified=True,
                    source_url=suggestion.source_url,
                    lat=location.lat,
                    lng=location.lng,
                )
            )
            if len(options) >= 3:
                break

        if not options:
            options.append(
                RecoveryOption(
                    code="SELECT_ROAD_ACCESSIBLE_ENDPOINT",
                    title="Chọn lại điểm tiếp cận có đường ô tô",
                    description=(
                        "Điểm tọa độ hiện tại bị Goong từ chối. Hãy chọn cổng, bãi xe hoặc điểm tham quan "
                        "gần đó từ danh sách Goong rồi lập kế hoạch lại."
                    ),
                    action="CHANGE_ENDPOINT",
                    verified=False,
                )
            )

        return ActionRequiredResponse(
            trip_id=trip_id,
            summary=(
                "Goong không thể định tuyến tới đúng tọa độ đích đã chọn. "
                "Hệ thống không tạo tuyến giả và đã chuẩn bị phương án đổi điểm tiếp cận."
            ),
            failure_category="ROUTING_ENDPOINT",
            provider="GOONG_DIRECTIONS",
            provider_status=failure.provider_status,
            http_status=failure.http_status,
            recovery_options=options,
            created_at=datetime.now(UTC),
        )
