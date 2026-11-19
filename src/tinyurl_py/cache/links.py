"""Cache of code -> where to redirect, in Redis (cache-aside).

Mongo is the source of truth; this is only a faster copy. So every Redis
problem is treated as "not cached" and never as an error: a redirect must keep
working, just a bit slower, when Redis is down.
"""

import logging
from datetime import UTC, datetime

from pydantic import AwareDatetime, BaseModel, ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

# How long a cached link may live. After that it is dropped and re-read from
# Mongo, which also limits how stale a copy can get.
DEFAULT_TTL_SECONDS = 3600

# What a deleted link leaves in the cache for a short while. A redirect that read
# the link from Mongo just before the deletion would otherwise write it back to
# the cache just after it; writes never replace an existing entry, so the marker
# wins. A minute is far longer than that window, and after it Mongo answers 404.
TOMBSTONE = "deleted"
TOMBSTONE_TTL_SECONDS = 60


class CachedLink(BaseModel):
    """Just what a redirect needs; not the whole Mongo document."""

    link_id: str  # Mongo _id as text; goes into the click event
    url: str
    mobile_url: str | None
    expires_at: AwareDatetime | None


def _key(code: str) -> str:
    return f"link:{code}"


def cache_ttl_seconds(expires_at: datetime | None, now: datetime | None = None) -> int:
    """Seconds a link may stay cached; 0 means "do not cache".

    Never longer than the time left until the link expires, otherwise the
    cache would keep redirecting after the link is supposed to be dead.
    """
    if expires_at is None:
        return DEFAULT_TTL_SECONDS
    now = now if now is not None else datetime.now(UTC)
    remaining = int((expires_at - now).total_seconds())
    return max(0, min(DEFAULT_TTL_SECONDS, remaining))


async def get_cached_link(redis: Redis, code: str) -> CachedLink | None:
    try:
        raw = await redis.get(_key(code))
    except RedisError:
        logger.warning("Redis read failed for %s; treating it as a cache miss", code)
        return None
    if raw is None or raw == TOMBSTONE:
        return None
    try:
        return CachedLink.model_validate_json(raw)
    except ValidationError:
        # A leftover in an old format. Removed, so the next write can replace it
        # (writes never overwrite an existing entry).
        logger.warning("Unreadable cache entry for %s; treating it as a miss", code)
        try:
            await redis.delete(_key(code))
        except RedisError:
            pass
        return None


async def cache_link(redis: Redis, code: str, link: CachedLink) -> None:
    ttl = cache_ttl_seconds(link.expires_at)
    if ttl <= 0:
        return
    try:
        # `ex` = expire after this many seconds; Redis deletes the entry itself.
        # `nx` = only if nothing is there: never over a deleted link's tombstone.
        await redis.set(_key(code), link.model_dump_json(), ex=ttl, nx=True)
    except RedisError:
        logger.warning("Redis write failed for %s; continuing without cache", code)


async def delete_cached_link(redis: Redis, code: str) -> None:
    """Replace the copy of a deleted link with a short-lived tombstone. If Redis is
    down the copy simply expires by itself within DEFAULT_TTL_SECONDS, so this is
    best effort."""
    try:
        await redis.set(_key(code), TOMBSTONE, ex=TOMBSTONE_TTL_SECONDS)
    except RedisError:
        logger.warning("Redis delete failed for %s; the cached copy will expire by itself", code)
