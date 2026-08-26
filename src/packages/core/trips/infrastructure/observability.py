from __future__ import annotations

from collections import defaultdict
from threading import RLock


class MetricsRegistry:
    """Small dependency-free registry suitable for logs or a metrics exporter."""

    def __init__(self):
        self._lock = RLock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._observations: dict[
            tuple[str, tuple[tuple[str, str], ...]], dict[str, float]
        ] = {}

    def increment(self, name: str, value: float = 1.0, **labels: object) -> None:
        key = (name, _labels(labels))
        with self._lock:
            self._counters[key] += value

    def gauge(self, name: str, value: float, **labels: object) -> None:
        key = (name, _labels(labels))
        with self._lock:
            self._gauges[key] = value

    def observe(self, name: str, value: float, **labels: object) -> None:
        key = (name, _labels(labels))
        with self._lock:
            current = self._observations.setdefault(
                key, {"count": 0.0, "sum": 0.0, "max": value}
            )
            current["count"] += 1
            current["sum"] += value
            current["max"] = max(current["max"], value)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "counters": {_key(name, labels): value for (name, labels), value in self._counters.items()},
                "gauges": {_key(name, labels): value for (name, labels), value in self._gauges.items()},
                "observations": {
                    _key(name, labels): dict(value)
                    for (name, labels), value in self._observations.items()
                },
            }


def _labels(values: dict[str, object]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((key, str(value)) for key, value in values.items()))


def _key(name: str, labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return name
    return f"{name}{{{','.join(f'{key}={value}' for key, value in labels)}}}"


metrics = MetricsRegistry()
