from __future__ import annotations

import httpx

from src.packages.contracts.places import (
    PlaceAutocompleteResponse,
    PlaceDetailResponse,
    PlacePrediction,
)
from src.packages.core.trips.application.errors import AppError


class GoongPlacesClient:
    """Server-side proxy for Goong Places so the REST key stays private."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://rsapi.goong.io",
        timeout_seconds: float = 4.0,
    ):
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def autocomplete(
        self,
        query: str,
        *,
        session_token: str | None = None,
        location: str | None = None,
        limit: int = 8,
    ) -> PlaceAutocompleteResponse:
        cleaned_query = query.strip()
        if len(cleaned_query) < 2:
            return PlaceAutocompleteResponse()

        params: dict[str, str | int | bool] = {
            "input": cleaned_query,
            "limit": limit,
            "more_compound": True,
            "api_key": self._require_api_key(),
        }
        if session_token:
            params["sessiontoken"] = session_token
        if location:
            params["location"] = location

        payload = self._get("/Place/AutoComplete", params=params)
        raw_predictions = payload.get("predictions") if isinstance(payload, dict) else None
        if not isinstance(raw_predictions, list):
            raise self._provider_error("Goong Places returned an unexpected autocomplete payload.")

        predictions: list[PlacePrediction] = []
        for item in raw_predictions:
            if not isinstance(item, dict):
                continue
            place_id = item.get("place_id")
            description = item.get("description")
            formatting = item.get("structured_formatting")
            if not isinstance(place_id, str) or not isinstance(description, str):
                continue
            formatting = formatting if isinstance(formatting, dict) else {}
            predictions.append(
                PlacePrediction(
                    place_id=place_id,
                    description=description,
                    main_text=str(formatting.get("main_text") or description.split(",")[0]),
                    secondary_text=str(formatting.get("secondary_text") or ""),
                )
            )
        return PlaceAutocompleteResponse(predictions=predictions)

    def detail(self, place_id: str, *, session_token: str | None = None) -> PlaceDetailResponse:
        cleaned_place_id = place_id.strip()
        if not cleaned_place_id:
            raise AppError(
                code="VALIDATION_ERROR",
                status_code=400,
                message="place_id is required.",
                details={"field": "place_id"},
            )

        params = {"place_id": cleaned_place_id, "api_key": self._require_api_key()}
        if session_token:
            params["sessiontoken"] = session_token
        payload = self._get("/Place/Detail", params=params)
        if not isinstance(payload, dict) or payload.get("status") != "OK":
            raise AppError(
                code="PLACE_NOT_FOUND",
                status_code=404,
                message="Goong could not resolve the selected place.",
                details={"provider": "GOONG_PLACES"},
            )

        result = payload.get("result")
        if not isinstance(result, dict):
            raise self._provider_error("Goong Places returned an unexpected detail payload.")
        geometry = result.get("geometry")
        location = geometry.get("location") if isinstance(geometry, dict) else None
        lat = location.get("lat") if isinstance(location, dict) else None
        lng = location.get("lng") if isinstance(location, dict) else None
        if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
            raise self._provider_error("Goong Places returned invalid coordinates.")

        name = result.get("name")
        address = result.get("formatted_address")
        return PlaceDetailResponse(
            place_id=str(result.get("place_id") or cleaned_place_id),
            name=str(name or address or "Địa điểm đã chọn"),
            formatted_address=str(address or name or "Địa điểm đã chọn"),
            lat=float(lat),
            lng=float(lng),
        )

    def _require_api_key(self) -> str:
        if not self._api_key:
            raise AppError(
                code="PROVIDER_NOT_CONFIGURED",
                status_code=503,
                message="GOONG_API_KEY is not configured.",
                details={"provider": "GOONG_PLACES"},
            )
        return self._api_key

    def _get(self, path: str, *, params: dict) -> object:
        try:
            response = httpx.get(
                f"{self._base_url}{path}",
                params=params,
                timeout=self._timeout_seconds,
                follow_redirects=True,
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise self._provider_error("Goong Places is unavailable right now.") from exc

    @staticmethod
    def _provider_error(message: str) -> AppError:
        return AppError(
            code="PLACE_PROVIDER_UNAVAILABLE",
            status_code=503,
            message=message,
            details={"provider": "GOONG_PLACES"},
        )

