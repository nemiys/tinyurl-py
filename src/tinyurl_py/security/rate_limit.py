"""Sliding-window rate limiter on Redis.

"At most `limit` requests in any `window_seconds` ending now." Unlike a fixed
window that resets on the clock, there is no boundary to exploit: 10 requests
one second before the minute changes and 10 one second after are still 20
requests within two seconds, and the second ten are refused.
"""

import logging
import math
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

# Runs inside Redis as ONE step that nobody can interleave with. Done as
# separate commands, two requests arriving together could both see "one place
# left" and both take it.
#
# The requests of one key live in a sorted set: member = a unique id per
# request, score = when it happened (milliseconds).
#
# KEYS[1] key
# ARGV    now_ms, window_ms, limit, unique id of this request
# Returns {allowed (1/0), requests still allowed, ms until a place frees up}
_SLIDING_WINDOW = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])

-- forget what has left the window
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)

local count = redis.call('ZCARD', key)
if count < limit then
  redis.call('ZADD', key, now, ARGV[4])
  -- an idle key disappears by itself once a whole window has passed
  redis.call('PEXPIRE', key, window)
  return {1, limit - count - 1, 0}
end

-- Refused. NOT recorded: otherwise whoever keeps hammering would stay blocked
-- forever. The oldest request in the window is the first to leave it.
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
return {0, 0, tonumber(oldest[2]) + window - now}
"""


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    remaining: int  # requests still allowed in the current window
    retry_after_seconds: int  # when refused: how long to wait; otherwise 0


class RateLimiter:
    def __init__(self, redis: Redis, *, clock: Callable[[], float] = time.time) -> None:
        self._script = redis.register_script(_SLIDING_WINDOW)
        # Injected so tests can move time by hand instead of sleeping. (With
        # several API servers, slightly different clocks blur the window by
        # that difference, which does not matter at this precision.)
        self._clock = clock

    async def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        now_ms = int(self._clock() * 1000)
        try:
            raw: Any = await self._script(
                keys=[f"ratelimit:{key}"],
                args=[now_ms, window_seconds * 1000, limit, uuid.uuid4().hex],
            )
        except RedisError:
            # Fail open: protection is a bonus, the service must keep working
            # while Redis is down.
            logger.warning("Rate limiter could not reach Redis; allowing %s", key)
            return RateLimitResult(allowed=True, remaining=limit, retry_after_seconds=0)

        allowed, remaining, wait_ms = raw
        # Rounded UP: waiting a fraction less than needed would just be refused again.
        retry_after = max(1, math.ceil(wait_ms / 1000)) if not allowed else 0
        return RateLimitResult(
            allowed=bool(allowed), remaining=int(remaining), retry_after_seconds=retry_after
        )
