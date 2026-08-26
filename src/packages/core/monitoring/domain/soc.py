from __future__ import annotations


def expected_soc_at_distance(
    soc_points: list[dict],
    distance_km: float,
    *,
    initial_soc_percent: float,
    final_soc_percent: float,
    route_distance_km: float,
) -> float:
    usable = [
        (float(item["distance_km"]), float(item["soc_percent"]), str(item.get("kind", "")))
        for item in soc_points
        if "distance_km" in item and "soc_percent" in item
    ]
    if not usable:
        ratio = 0.0 if route_distance_km <= 0 else min(1.0, max(0.0, distance_km / route_distance_km))
        return initial_soc_percent + (final_soc_percent - initial_soc_percent) * ratio

    usable.sort(key=lambda item: (item[0], 0 if item[2] == "ARRIVAL" else 1))
    if distance_km <= usable[0][0]:
        return usable[0][1]
    for left, right in zip(usable, usable[1:]):
        if distance_km <= right[0]:
            span = right[0] - left[0]
            if span <= 0:
                return right[1]
            ratio = (distance_km - left[0]) / span
            return left[1] + (right[1] - left[1]) * ratio
    return usable[-1][1]

