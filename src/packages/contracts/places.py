from pydantic import BaseModel, Field


class PlacePrediction(BaseModel):
    place_id: str
    description: str
    main_text: str = ""
    secondary_text: str = ""


class PlaceAutocompleteResponse(BaseModel):
    predictions: list[PlacePrediction] = Field(default_factory=list)


class PlaceDetailResponse(BaseModel):
    place_id: str
    name: str
    formatted_address: str
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    provider: str = "GOONG_PLACES"

