import pytest

from src.packages.core.trips.application.errors import AppError
from src.packages.core.trips.infrastructure.goong_places import GoongPlacesClient


class StubResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_goong_places_autocomplete_maps_public_contract(monkeypatch):
    def fake_get(url, *, params, timeout, follow_redirects):
        assert url.endswith("/Place/AutoComplete")
        assert params["sessiontoken"] == "session-1"
        return StubResponse(
            {
                "predictions": [
                    {
                        "place_id": "place-1",
                        "description": "91 Trung Kính, Hà Nội",
                        "structured_formatting": {
                            "main_text": "91 Trung Kính",
                            "secondary_text": "Hà Nội",
                        },
                    }
                ]
            }
        )

    monkeypatch.setattr("src.packages.core.trips.infrastructure.goong_places.httpx.get", fake_get)
    client = GoongPlacesClient(api_key="private-key")

    response = client.autocomplete("91 Trung Kính", session_token="session-1")

    assert response.predictions[0].place_id == "place-1"
    assert response.predictions[0].main_text == "91 Trung Kính"


def test_goong_places_detail_maps_coordinates(monkeypatch):
    def fake_get(url, *, params, timeout, follow_redirects):
        assert url.endswith("/Place/Detail")
        assert params["place_id"] == "place-1"
        return StubResponse(
            {
                "status": "OK",
                "result": {
                    "place_id": "place-1",
                    "name": "91 Trung Kính",
                    "formatted_address": "91 Trung Kính, Hà Nội",
                    "geometry": {"location": {"lat": 21.01376, "lng": 105.79827}},
                },
            }
        )

    monkeypatch.setattr("src.packages.core.trips.infrastructure.goong_places.httpx.get", fake_get)
    client = GoongPlacesClient(api_key="private-key")

    detail = client.detail("place-1")

    assert detail.provider == "GOONG_PLACES"
    assert detail.lat == 21.01376
    assert detail.lng == 105.79827


def test_goong_places_fails_closed_without_key():
    client = GoongPlacesClient(api_key="")

    with pytest.raises(AppError) as exc_info:
        client.autocomplete("Hà Nội")

    assert exc_info.value.code == "PROVIDER_NOT_CONFIGURED"
