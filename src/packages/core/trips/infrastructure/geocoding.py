from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

import httpx

from src.packages.contracts.trips import AmbiguousLocationCandidate
from src.packages.core.trips.application.errors import AmbiguousLocationError, AppError


def normalize_text(value: str) -> str:
    sanitized = value.replace("\u0111", "d").replace("\u0110", "D")
    ascii_value = unicodedata.normalize("NFKD", sanitized).encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_value.lower().strip().split())


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius * c


@dataclass(frozen=True)
class GeocodeEntry:
    name: str
    formatted_address: str
    lat: float
    lng: float
    aliases: tuple[str, ...] = ()


class InMemoryGeocoder:
    def __init__(self):
        self._entries = (
            GeocodeEntry("Ha Noi", "Ha Noi, Viet Nam", 21.0278, 105.8342, ("ha noi", "hanoi", "ha noi, viet nam")),
            GeocodeEntry("Vinh", "Vinh, Nghe An, Viet Nam", 18.6796, 105.6813, ("vinh", "vinh, nghe an")),
            GeocodeEntry("Da Nang", "Da Nang, Viet Nam", 16.0544, 108.2022, ("da nang", "danang", "da nang, viet nam")),
            GeocodeEntry("Hoa Binh", "Hoa Binh, Viet Nam", 20.8133, 105.3383, ("hoa binh", "hoa binh, viet nam")),
            GeocodeEntry(
                "Hoang Mai, Ha Noi",
                "Hoang Mai, Ha Noi, Viet Nam",
                20.9740,
                105.8645,
                ("hoang mai", "hoang mai, ha noi"),
            ),
            GeocodeEntry(
                "Hoang Mai, Nghe An",
                "Hoang Mai, Nghe An, Viet Nam",
                19.2922,
                105.7188,
                ("hoang mai", "hoang mai, nghe an"),
            ),
        )

    @lru_cache(maxsize=128)
    def resolve_text(self, query: str, field_name: str) -> GeocodeEntry:
        normalized_query = normalize_text(query)
        matches: list[tuple[GeocodeEntry, float]] = []

        for entry in self._entries:
            confidence = score_entry(entry, normalized_query)
            if confidence > 0:
                matches.append((entry, confidence))

        if not matches:
            raise_location_not_found(field_name)

        matches.sort(key=lambda item: item[1], reverse=True)
        top_confidence = matches[0][1]
        top_matches = [entry for entry, confidence in matches if confidence == top_confidence]

        if len(top_matches) >= 2 and has_far_apart_candidates(top_matches):
            raise AmbiguousLocationError(
                field_name,
                [
                    AmbiguousLocationCandidate(
                        label=entry.formatted_address,
                        lat=entry.lat,
                        lng=entry.lng,
                    ).model_dump()
                    for entry in top_matches
                ],
            )

        return matches[0][0]


class NominatimGeocoder:
    def __init__(
        self,
        *,
        base_url: str,
        country_codes: str,
        user_agent: str,
        timeout_seconds: float,
        result_limit: int,
    ):
        self._base_url = base_url.rstrip("/")
        self._country_codes = country_codes.strip()
        self._headers = {
            "User-Agent": user_agent,
            "Accept": "application/json",
            "Accept-Language": "vi,en",
        }
        self._timeout_seconds = timeout_seconds
        self._result_limit = result_limit

    @lru_cache(maxsize=256)
    def resolve_text(self, query: str, field_name: str) -> GeocodeEntry:
        cleaned_query = query.strip()
        if not cleaned_query:
            raise_location_not_found(field_name)

        entries = self._search_entries(cleaned_query, field_name)
        if not entries:
            raise_location_not_found(field_name)

        ranked_matches = self._rank_entries(cleaned_query, entries)
        best_entry, best_score = ranked_matches[0]
        if best_score <= 0:
            raise_location_not_found(field_name)

        equally_strong = [entry for entry, score in ranked_matches if math.isclose(score, best_score, abs_tol=0.01)]
        if best_score >= 0.98 and len(equally_strong) >= 2 and has_far_apart_candidates(equally_strong):
            raise AmbiguousLocationError(
                field_name,
                [
                    AmbiguousLocationCandidate(
                        label=entry.formatted_address,
                        lat=entry.lat,
                        lng=entry.lng,
                    ).model_dump()
                    for entry in equally_strong
                ],
            )

        return best_entry

    def _search_entries(self, query: str, field_name: str) -> list[GeocodeEntry]:
        params = {
            "q": query,
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": self._result_limit,
        }
        if self._country_codes:
            params["countrycodes"] = self._country_codes

        try:
            with httpx.Client(timeout=self._timeout_seconds, headers=self._headers, follow_redirects=True) as client:
                response = client.get(f"{self._base_url}/search", params=params)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AppError(
                code="INTERNAL_ERROR",
                status_code=500,
                message="Geocoding provider is unavailable right now.",
                details={"field": field_name, "reason": "GEOCODER_UNAVAILABLE"},
            ) from exc

        payload = response.json()
        if not isinstance(payload, list):
            raise AppError(
                code="INTERNAL_ERROR",
                status_code=500,
                message="Geocoding provider returned an unexpected payload.",
                details={"field": field_name, "reason": "GEOCODER_BAD_PAYLOAD"},
            )

        entries: list[GeocodeEntry] = []
        for item in payload:
            entry = self._to_entry(item)
            if entry is not None:
                entries.append(entry)

        return dedupe_nearby_entries(entries)

    def _rank_entries(self, query: str, entries: list[GeocodeEntry]) -> list[tuple[GeocodeEntry, float]]:
        normalized_query = normalize_text(query)
        ranked = [(entry, score_entry(entry, normalized_query)) for entry in entries]
        ranked.sort(key=lambda item: item[1], reverse=True)
        return ranked

    def _to_entry(self, item: object) -> GeocodeEntry | None:
        if not isinstance(item, dict):
            return None

        display_name = item.get("display_name")
        lat = parse_coordinate(item.get("lat"))
        lng = parse_coordinate(item.get("lon"))
        if not isinstance(display_name, str) or lat is None or lng is None:
            return None

        address = item.get("address") if isinstance(item.get("address"), dict) else {}
        name = first_non_empty_string(
            item.get("name"),
            address.get("city"),
            address.get("town"),
            address.get("village"),
            address.get("county"),
            display_name.split(",")[0],
        )

        aliases = [display_name, name]
        for value in address.values():
            if isinstance(value, str):
                aliases.append(value)

        return GeocodeEntry(
            name=name,
            formatted_address=display_name,
            lat=lat,
            lng=lng,
            aliases=tuple(dict.fromkeys(alias for alias in aliases if alias)),
        )


class GoongGeocoder:
    """Server-side forward geocoding through Goong for non-browser clients."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://rsapi.goong.io",
        timeout_seconds: float = 4.0,
        result_limit: int = 5,
    ):
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._result_limit = result_limit

    @lru_cache(maxsize=256)
    def resolve_text(self, query: str, field_name: str) -> GeocodeEntry:
        cleaned_query = query.strip()
        if not cleaned_query:
            raise_location_not_found(field_name)
        if not self._api_key:
            raise AppError(
                code="INTERNAL_ERROR",
                status_code=500,
                message="Goong geocoding is not configured.",
                details={"field": field_name, "reason": "GOONG_API_KEY_MISSING"},
            )

        try:
            response = httpx.get(
                f"{self._base_url}/Geocode",
                params={
                    "address": cleaned_query,
                    "api_key": self._api_key,
                },
                timeout=self._timeout_seconds,
                follow_redirects=True,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AppError(
                code="INTERNAL_ERROR",
                status_code=500,
                message="Goong Geocoding API is unavailable right now.",
                details={"field": field_name, "reason": "GEOCODER_UNAVAILABLE"},
            ) from exc

        if not isinstance(payload, dict):
            raise AppError(
                code="INTERNAL_ERROR",
                status_code=500,
                message="Goong Geocoding API returned an unexpected payload.",
                details={"field": field_name, "reason": "GEOCODER_BAD_PAYLOAD"},
            )

        status = payload.get("status")
        if status == "ZERO_RESULTS":
            raise_location_not_found(field_name)
        if status != "OK":
            raise AppError(
                code="INTERNAL_ERROR",
                status_code=500,
                message="Goong Geocoding API rejected the request.",
                details={"field": field_name, "reason": str(status or "UNKNOWN")},
            )

        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise_location_not_found(field_name)

        entries: list[GeocodeEntry] = []
        for result in raw_results[: self._result_limit]:
            entry = self._to_entry(result)
            if entry is not None:
                entries.append(entry)
        entries = dedupe_nearby_entries(entries)
        if not entries:
            raise_location_not_found(field_name)

        normalized_query = normalize_text(cleaned_query)
        ranked = sorted(
            ((entry, score_entry(entry, normalized_query)) for entry in entries),
            key=lambda item: item[1],
            reverse=True,
        )
        best_entry, best_score = ranked[0]
        equally_strong = [entry for entry, score in ranked if math.isclose(score, best_score, abs_tol=0.01)]
        if len(equally_strong) >= 2 and has_far_apart_candidates(equally_strong):
            raise AmbiguousLocationError(
                field_name,
                [
                    AmbiguousLocationCandidate(
                        label=entry.formatted_address,
                        lat=entry.lat,
                        lng=entry.lng,
                    ).model_dump()
                    for entry in equally_strong
                ],
            )
        return best_entry

    @staticmethod
    def _to_entry(item: object) -> GeocodeEntry | None:
        if not isinstance(item, dict):
            return None
        formatted_address = item.get("formatted_address")
        location = item.get("geometry", {}).get("location", {})
        lat = parse_coordinate(location.get("lat")) if isinstance(location, dict) else None
        lng = parse_coordinate(location.get("lng")) if isinstance(location, dict) else None
        if not isinstance(formatted_address, str) or lat is None or lng is None:
            return None

        components = item.get("address_components")
        aliases = [formatted_address]
        if isinstance(components, list):
            for component in components:
                if isinstance(component, dict):
                    aliases.extend(
                        value
                        for value in (component.get("long_name"), component.get("short_name"))
                        if isinstance(value, str)
                    )
        name = formatted_address.split(",")[0].strip()
        aliases.append(name)
        return GeocodeEntry(
            name=name,
            formatted_address=formatted_address,
            lat=lat,
            lng=lng,
            aliases=tuple(dict.fromkeys(aliases)),
        )


def parse_coordinate(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def first_non_empty_string(*values: object) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Unknown"


def score_entry(entry: GeocodeEntry, normalized_query: str) -> float:
    normalized_name = normalize_text(entry.name)
    normalized_label = normalize_text(entry.formatted_address)
    normalized_aliases = {normalize_text(alias) for alias in entry.aliases}
    query_tokens = [token for token in normalized_query.split(" ") if token]

    if normalized_query in normalized_aliases or normalized_query == normalized_name:
        return 1.0
    if normalized_label == normalized_query or normalized_label.startswith(f"{normalized_query},"):
        return 0.99
    if query_tokens and all(token in normalized_label for token in query_tokens):
        return 0.86
    if query_tokens:
        overlap = sum(1 for token in query_tokens if token in normalized_label) / len(query_tokens)
        if overlap >= 0.75:
            return 0.72
    return 0.0


def dedupe_nearby_entries(entries: list[GeocodeEntry], radius_km: float = 35.0) -> list[GeocodeEntry]:
    deduped: list[GeocodeEntry] = []
    for entry in entries:
        normalized_name = normalize_text(entry.name)
        is_duplicate = False

        for existing in deduped:
            if normalize_text(existing.formatted_address) == normalize_text(entry.formatted_address):
                is_duplicate = True
                break
            if normalized_name == normalize_text(existing.name) and distance_km(
                existing.lat,
                existing.lng,
                entry.lat,
                entry.lng,
            ) <= radius_km:
                is_duplicate = True
                break

        if not is_duplicate:
            deduped.append(entry)

    return deduped


def has_far_apart_candidates(entries: list[GeocodeEntry], minimum_distance_km: float = 60.0) -> bool:
    if len(entries) < 2:
        return False

    for index, entry in enumerate(entries):
        for other in entries[index + 1 :]:
            if distance_km(entry.lat, entry.lng, other.lat, other.lng) >= minimum_distance_km:
                return True
    return False


def raise_location_not_found(field_name: str) -> None:
    raise AppError(
        code="VALIDATION_ERROR",
        status_code=400,
        message=f"Could not geocode the {field_name} address.",
        details={"field": field_name, "reason": "LOCATION_NOT_FOUND"},
    )
