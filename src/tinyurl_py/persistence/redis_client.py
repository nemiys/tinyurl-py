"""Redis connection helper (named redis_client to avoid clashing with the `redis` package)."""

from redis.asyncio import Redis, from_url

from tinyurl_py.settings import settings


def create_redis() -> Redis:
    # Redis is only a cache here, so a dead Redis must fail FAST: with short
    # timeouts a redirect falls back to Mongo in half a second instead of
    # hanging. The client connects lazily, on first use.
    # decode_responses: values come back as text instead of raw bytes.
    return from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )
