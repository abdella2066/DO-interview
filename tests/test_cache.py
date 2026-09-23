import os
import time

import pytest

from app.cache import MemoryCache, RedisCache

TEST_CACHE_URL = os.getenv("TEST_CACHE_URL")


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


async def test_memory_cache_round_trip():
    cache = MemoryCache()

    await cache.set("key", "value", ttl_seconds=60)
    assert await cache.get("key") == "value"

    await cache.delete("key")
    assert await cache.get("key") is None


async def test_memory_cache_entries_expire_after_ttl():
    clock = FakeClock()
    cache = MemoryCache(clock=clock)
    await cache.set("key", "value", ttl_seconds=60)

    clock.now += 59
    assert await cache.get("key") == "value"

    clock.now += 1
    assert await cache.get("key") is None


async def test_memory_cache_evicts_the_oldest_entry_when_full():
    cache = MemoryCache(max_entries=2)
    await cache.set("a", "1", ttl_seconds=60)
    await cache.set("b", "2", ttl_seconds=60)
    await cache.set("c", "3", ttl_seconds=60)

    assert await cache.get("a") is None
    assert await cache.get("b") == "2"
    assert await cache.get("c") == "3"


async def test_redis_cache_fails_open_and_fast_when_unreachable():
    cache = RedisCache("redis://localhost:1/0")
    started = time.perf_counter()

    assert await cache.get("key") is None
    await cache.set("key", "value", ttl_seconds=60)
    await cache.delete("key")
    assert await cache.ping() is False

    # No retry storm: redis-py's default policy (10 retries with backoff) would take seconds.
    assert time.perf_counter() - started < 1.0
    await cache.close()


@pytest.mark.skipif(not TEST_CACHE_URL, reason="TEST_CACHE_URL is not set")
async def test_redis_cache_round_trip():
    cache = RedisCache(TEST_CACHE_URL)

    await cache.set("test:key", "value", ttl_seconds=60)
    assert await cache.get("test:key") == "value"
    assert await cache.ping() is True

    await cache.delete("test:key")
    assert await cache.get("test:key") is None
    await cache.close()
