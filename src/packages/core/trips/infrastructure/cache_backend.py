from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock, RLock
from typing import Protocol


class CacheBackendError(RuntimeError):
    """A cache failure that callers may safely treat as a cache miss."""


class CacheBackend(Protocol):
    def get(self, key: str) -> bytes | None: ...

    def set(self, key: str, value: bytes, *, ttl_seconds: float) -> None: ...

    def delete(self, key: str) -> None: ...

    def lock(self, key: str, *, timeout_seconds: float = 10.0): ...


class InMemoryCacheBackend:
    """Thread-safe TTL cache used by tests and single-process development."""

    def __init__(self, *, max_entries: int = 1024):
        self._max_entries = max(1, max_entries)
        self._values: dict[str, tuple[float, bytes]] = {}
        self._guard = RLock()
        self._locks: dict[str, Lock] = {}

    def get(self, key: str) -> bytes | None:
        now = time.monotonic()
        with self._guard:
            cached = self._values.get(key)
            if cached is None:
                return None
            expires_at, value = cached
            if expires_at <= now:
                self._values.pop(key, None)
                return None
            return value

    def set(self, key: str, value: bytes, *, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            return
        with self._guard:
            if len(self._values) >= self._max_entries and key not in self._values:
                oldest_key = min(self._values, key=lambda item: self._values[item][0])
                self._values.pop(oldest_key, None)
            self._values[key] = (time.monotonic() + ttl_seconds, bytes(value))

    def delete(self, key: str) -> None:
        with self._guard:
            self._values.pop(key, None)

    @contextmanager
    def lock(self, key: str, *, timeout_seconds: float = 10.0) -> Iterator[None]:
        with self._guard:
            item_lock = self._locks.setdefault(key, Lock())
        acquired = item_lock.acquire(timeout=max(0.0, timeout_seconds))
        if not acquired:
            raise CacheBackendError(f"Timed out acquiring cache lock: {key}")
        try:
            yield
        finally:
            item_lock.release()


class RedisCacheBackend:
    """Redis implementation isolated behind the cache port.

    Redis is imported lazily so a disabled cache never becomes an application
    startup dependency. All driver failures are normalized for fail-open use.
    """

    def __init__(self, url: str, *, client=None):
        if client is not None:
            self._client = client
            return
        try:
            import redis
        except ImportError as exc:  # pragma: no cover - deployment packaging guard
            raise CacheBackendError(
                "REDIS_CACHE_ENABLED requires the 'redis' package."
            ) from exc
        self._client = redis.Redis.from_url(url)

    def get(self, key: str) -> bytes | None:
        try:
            value = self._client.get(key)
            if value is None:
                return None
            return value.encode() if isinstance(value, str) else bytes(value)
        except Exception as exc:
            raise CacheBackendError("Redis GET failed.") from exc

    def set(self, key: str, value: bytes, *, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            return
        try:
            self._client.set(key, value, px=max(1, round(ttl_seconds * 1000)))
        except Exception as exc:
            raise CacheBackendError("Redis SET failed.") from exc

    def delete(self, key: str) -> None:
        try:
            self._client.delete(key)
        except Exception as exc:
            raise CacheBackendError("Redis DELETE failed.") from exc

    @contextmanager
    def lock(self, key: str, *, timeout_seconds: float = 10.0) -> Iterator[None]:
        try:
            lock = self._client.lock(
                key,
                timeout=max(1.0, timeout_seconds),
                blocking_timeout=max(0.0, timeout_seconds),
            )
            acquired = lock.acquire(blocking=True)
        except Exception as exc:
            raise CacheBackendError("Redis lock acquisition failed.") from exc
        if not acquired:
            raise CacheBackendError(f"Timed out acquiring Redis lock: {key}")
        try:
            yield
        finally:
            try:
                lock.release()
            except Exception as exc:
                raise CacheBackendError("Redis lock release failed.") from exc
