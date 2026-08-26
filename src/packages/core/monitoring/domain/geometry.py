from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1 = map(math.radians, a)
    lat2, lng2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(value))


def point_along_polyline(polyline: list[list[float]], fraction: float) -> tuple[float, float, float]:
    if not polyline:
        raise ValueError("Route polyline is empty.")
    if len(polyline) == 1:
        return float(polyline[0][0]), float(polyline[0][1]), 0.0
    fraction = min(1.0, max(0.0, fraction))
    segments = [
        haversine_km((float(a[0]), float(a[1])), (float(b[0]), float(b[1])))
        for a, b in zip(polyline, polyline[1:])
    ]
    total = sum(segments)
    if total <= 0:
        return float(polyline[0][0]), float(polyline[0][1]), 0.0
    target = total * fraction
    walked = 0.0
    for index, length in enumerate(segments):
        if walked + length >= target or index == len(segments) - 1:
            local = 0.0 if length <= 0 else (target - walked) / length
            start, end = polyline[index], polyline[index + 1]
            lat = float(start[0]) + (float(end[0]) - float(start[0])) * local
            lng = float(start[1]) + (float(end[1]) - float(start[1])) * local
            return lat, lng, target
        walked += length
    return float(polyline[-1][0]), float(polyline[-1][1]), total


def offset_perpendicular(
    polyline: list[list[float]],
    fraction: float,
    distance_km: float,
) -> tuple[float, float]:
    lat, lng, _ = point_along_polyline(polyline, fraction)
    before_lat, before_lng, _ = point_along_polyline(polyline, max(0.0, fraction - 0.01))
    after_lat, after_lng, _ = point_along_polyline(polyline, min(1.0, fraction + 0.01))
    km_per_lng = 111.195 * max(0.01, math.cos(math.radians(lat)))
    dx = (after_lng - before_lng) * km_per_lng
    dy = (after_lat - before_lat) * 111.195
    norm = math.hypot(dx, dy)
    if norm <= 1e-9:
        return lat + distance_km / 111.195, lng
    normal_x, normal_y = -dy / norm, dx / norm
    return lat + normal_y * distance_km / 111.195, lng + normal_x * distance_km / km_per_lng


def distance_to_polyline_km(lat: float, lng: float, polyline: list[list[float]]) -> float:
    if not polyline:
        raise ValueError("Route polyline is empty.")
    if len(polyline) == 1:
        return haversine_km((lat, lng), (float(polyline[0][0]), float(polyline[0][1])))

    ref_lat = math.radians(lat)
    km_per_lat = 111.195
    km_per_lng = 111.195 * max(0.01, math.cos(ref_lat))

    def xy(point: list[float]) -> tuple[float, float]:
        return (float(point[1]) - lng) * km_per_lng, (float(point[0]) - lat) * km_per_lat

    best = float("inf")
    for start, end in zip(polyline, polyline[1:]):
        ax, ay = xy(start)
        bx, by = xy(end)
        vx, vy = bx - ax, by - ay
        denominator = vx * vx + vy * vy
        t = 0.0 if denominator <= 0 else max(0.0, min(1.0, -(ax * vx + ay * vy) / denominator))
        px, py = ax + t * vx, ay + t * vy
        best = min(best, math.hypot(px, py))
    return best
