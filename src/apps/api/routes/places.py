from fastapi import APIRouter, Depends, Query

from src.packages.contracts.errors import ErrorEnvelope
from src.packages.contracts.places import PlaceAutocompleteResponse, PlaceDetailResponse
from src.packages.core.trips.api.dependencies import get_goong_places_client
from src.packages.core.trips.infrastructure.goong_places import GoongPlacesClient

router = APIRouter(prefix="/places", tags=["places"])


@router.get(
    "/autocomplete",
    response_model=PlaceAutocompleteResponse,
    responses={503: {"model": ErrorEnvelope}},
)
def autocomplete_places(
    input: str = Query(..., min_length=2, max_length=200),
    session_token: str | None = Query(default=None, max_length=100),
    location: str | None = Query(default=None, pattern=r"^-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?$"),
    limit: int = Query(default=8, ge=1, le=10),
    places: GoongPlacesClient = Depends(get_goong_places_client),
) -> PlaceAutocompleteResponse:
    return places.autocomplete(
        input,
        session_token=session_token,
        location=location,
        limit=limit,
    )


@router.get(
    "/detail",
    response_model=PlaceDetailResponse,
    responses={404: {"model": ErrorEnvelope}, 503: {"model": ErrorEnvelope}},
)
def get_place_detail(
    place_id: str = Query(..., min_length=1, max_length=2000),
    session_token: str | None = Query(default=None, max_length=100),
    places: GoongPlacesClient = Depends(get_goong_places_client),
) -> PlaceDetailResponse:
    return places.detail(place_id, session_token=session_token)

