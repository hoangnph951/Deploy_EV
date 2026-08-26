from dataclasses import dataclass

from src.packages.core.trips.application.recovery_supervisor import RecoverySupervisor
from src.packages.core.trips.infrastructure.openai_recovery import EndpointRecoverySuggestion
from src.packages.core.trips.infrastructure.routing import RoutingResult, RoutingUnavailableError


@dataclass(frozen=True)
class Location:
    formatted_address: str
    lat: float
    lng: float


class Advisor:
    def suggest_endpoint_access(self, **kwargs):
        return [
            EndpointRecoverySuggestion("Blocked", "Bad road", "https://example.com/bad", "Bad"),
            EndpointRecoverySuggestion("Visitor gate", "Good road", "https://example.com/good", "Gate"),
        ]


class Geocoder:
    def resolve_text(self, query, field_name):
        if "Blocked" in query:
            return Location("Blocked", 8.0, 104.0)
        return Location("Visitor gate", 8.6, 104.7)


class Router:
    def get_route(self, origin_lat, origin_lng, dest_lat, dest_lng, waypoints=None):
        if dest_lat == 8.0:
            raise RoutingUnavailableError(
                "not found", http_status=400, provider_status="NOT_FOUND", retryable=False
            )
        return RoutingResult(polyline=[[origin_lat, origin_lng], [dest_lat, dest_lng]], distance_km=1, duration_min=1)


def test_supervisor_returns_only_goong_verified_access_points() -> None:
    result = RecoverySupervisor(
        advisor=Advisor(), geocoder=Geocoder(), routing_provider=Router()
    ).recover_routing_endpoint(
        trip_id="trip-1",
        origin_name="Hà Giang",
        origin_lat=23.0,
        origin_lng=105.0,
        destination_name="Đất Mũi",
        destination_lat=8.61,
        destination_lng=104.79,
        failure=RoutingUnavailableError(
            "not found", http_status=400, provider_status="NOT_FOUND", retryable=False
        ),
    )

    assert result is not None
    assert result.outcome == "ACTION_REQUIRED"
    assert len(result.recovery_options) == 1
    assert result.recovery_options[0].title == "Visitor gate"
    assert result.recovery_options[0].verified is True
