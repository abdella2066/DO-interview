"""Cache backends behind one small interface.

RedisCache (Valkey or Redis) is shared by every app instance, so one invalidation reaches all of
them. MemoryCache lives inside a single process: fine for tests, local runs, and one instance.
Both fail open: a cache problem never fails a request, it only costs a database read.
"""

import logging
import time
from collections.abc import Callable
from typing import Protocol

import redis.asyncio as redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

logger = logging.getLogger(__name__)

CACHE_ERRORS = (redis.RedisError, OSError)


class Cache(Protocol):
    backend: str

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ttl_seconds: int) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def ping(self) -> bool: ...

    async def close(self) -> None: ...


class MemoryCache:
    """Per-process TTL cache. Expired entries are dropped when read; total size is capped."""

    backend = "memory"

    def __init__(
        self, max_entries: int = 10_000, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._entries: dict[str, tuple[float, str]] = {}
        self._max_entries = max_entries
        self._clock = clock

    async def get(self, key: str) -> str | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= self._clock():
            del self._entries[key]
            return None
        return value

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        if key not in self._entries and len(self._entries) >= self._max_entries:
            del self._entries[next(iter(self._entries))]  # evict the oldest insertion
        self._entries[key] = (self._clock() + ttl_seconds, value)

    async def delete(self, key: str) -> None:
        self._entries.pop(key, None)

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        self._entries.clear()


class RedisCache:
    """Valkey/Redis cache with short socket timeouts, so an outage can't stall requests."""

    backend = "redis"

    def __init__(self, url: str) -> None:
        self._client = redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
            # redis-py retries 10 times with backoff by default; a fail-open cache must fail fast.
            retry=Retry(NoBackoff(), retries=0),
        )

    async def get(self, key: str) -> str | None:
        try:
            return await self._client.get(key)
        except CACHE_ERRORS as exc:
            logger.warning("Cache read failed, falling back to the database: %s", exc)
            return None

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        try:
            await self._client.set(key, value, ex=ttl_seconds)
        except CACHE_ERRORS as exc:
            logger.warning("Cache write failed: %s", exc)

    async def delete(self, key: str) -> None:
        try:
            await self._client.delete(key)
        except CACHE_ERRORS as exc:
            logger.error("Cache invalidation failed; %s may be stale until its TTL: %s", key, exc)

    async def ping(self) -> bool:
        try:
            return bool(await self._client.ping())
        except CACHE_ERRORS:
            return False

    async def close(self) -> None:
        await self._client.aclose()


def build_cache(cache_url: str | None) -> Cache:
    return RedisCache(cache_url) if cache_url else MemoryCache()
