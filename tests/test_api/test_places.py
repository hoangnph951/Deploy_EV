import pytest

from src.apps.api.main import app
from src.packages.contracts.places import (
    PlaceAutocompleteResponse,
    PlaceDetailResponse,
    PlacePrediction,
)
from src.packages.core.trips.api.dependencies import get_goong_places_client


class StubPlacesClient:
    def autocomplete(self, query, *, session_token=None, location=None, limit=8):
        assert query == "Trung Kính"
        assert session_token == "session-1"
        return PlaceAutocompleteResponse(
            predictions=[
                PlacePrediction(
                    place_id="place-1",
                    description="91 Trung Kính, Hà Nội",
                    main_text="91 Trung Kính",
                    secondary_text="Hà Nội",
                )
            ]
        )

    def detail(self, place_id, *, session_token=None):
        assert place_id == "place-1"
        return PlaceDetailResponse(
            place_id=place_id,
            name="91 Trung Kính",
            formatted_address="91 Trung Kính, Hà Nội",
            lat=21.01376,
            lng=105.79827,
        )


@pytest.mark.asyncio
async def test_places_endpoints_return_frontend_contract(client):
    app.dependency_overrides[get_goong_places_client] = lambda: StubPlacesClient()
    try:
        autocomplete = await client.get(
            "/api/v1/places/autocomplete",
            params={"input": "Trung Kính", "session_token": "session-1"},
        )
        detail = await client.get(
            "/api/v1/places/detail",
            params={"place_id": "place-1", "session_token": "session-1"},
        )
    finally:
        app.dependency_overrides.pop(get_goong_places_client, None)

    assert autocomplete.status_code == 200
    assert autocomplete.json()["predictions"][0]["place_id"] == "place-1"
    assert detail.status_code == 200
    assert detail.json()["provider"] == "GOONG_PLACES"
    assert detail.json()["lat"] == 21.01376
