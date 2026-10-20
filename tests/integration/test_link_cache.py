"""The link cache against a real Redis (database 15, wiped around each test).

Needs the Redis container from docker-compose.yml running.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from redis.asyncio import Redis, from_url

from tinyurl_py.cache.links import CachedLink, cache_link, get_cached_link
from tinyurl_py.settings import settings

LINK = CachedLink(
    link_id="1",
    url="https://example.com/page",
    mobile_url="https://m.example.com/",
    expires_at=None,
)


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
    client = from_url(settings.redis_url, db=15, decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


async def test_redis_answers_ping(redis_client: Redis) -> None:
    assert await redis_client.ping() is True


async def test_cached_link_comes_back_unchanged(redis_client: Redis) -> None:
    expires_at = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)
    link = CachedLink(
        link_id="1", url="https://example.com/", mobile_url=None, expires_at=expires_at
    )

    await cache_link(redis_client, "aB3dE9x", link)

    assert await get_cached_link(redis_client, "aB3dE9x") == link


async def test_unknown_code_is_a_cache_miss(redis_client: Redis) -> None:
    assert await get_cached_link(redis_client, "nothere") is None


async def test_entry_is_stored_with_a_time_limit(redis_client: Redis) -> None:
    await cache_link(redis_client, "aB3dE9x", LINK)

    ttl = await redis_client.ttl("link:aB3dE9x")
    assert 0 < ttl <= 3600


async def test_entry_does_not_outlive_the_link(redis_client: Redis) -> None:
    soon = CachedLink(
        link_id="1",
        url="https://example.com/",
        mobile_url=None,
        expires_at=datetime.now(UTC) + timedelta(seconds=120),
    )

    await cache_link(redis_client, "aB3dE9x", soon)

    assert 0 < await redis_client.ttl("link:aB3dE9x") <= 120


async def test_already_expired_link_is_not_cached(redis_client: Redis) -> None:
    gone = CachedLink(
        link_id="1",
        url="https://example.com/",
        mobile_url=None,
        expires_at=datetime.now(UTC) - timedelta(seconds=5),
    )

    await cache_link(redis_client, "aB3dE9x", gone)

    assert await redis_client.exists("link:aB3dE9x") == 0


async def test_a_dead_redis_never_breaks_the_caller() -> None:
    dead = from_url("redis://localhost:1", socket_connect_timeout=0.5)

    assert await get_cached_link(dead, "aB3dE9x") is None  # a miss, not an error
    await cache_link(dead, "aB3dE9x", LINK)  # silently skipped

    await dead.aclose()
