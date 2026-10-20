"""The sliding-window rate limiter against a real Redis (database 15).

Time comes from a fake clock that the tests move by hand, so nothing sleeps.
Needs the Redis container from docker-compose.yml.
"""

import asyncio

from redis.asyncio import Redis, from_url

from tinyurl_py.security.rate_limit import RateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_limiter(redis: Redis) -> tuple[RateLimiter, FakeClock]:
    clock = FakeClock()
    return RateLimiter(redis, clock=clock), clock


async def test_requests_up_to_the_limit_are_allowed_then_refused(redis_client: Redis) -> None:
    limiter, _ = make_limiter(redis_client)

    results = [await limiter.check("user:1", limit=3, window_seconds=60) for _ in range(4)]

    assert [result.allowed for result in results] == [True, True, True, False]
    assert [result.remaining for result in results] == [2, 1, 0, 0]


async def test_a_refused_request_is_not_recorded(redis_client: Redis) -> None:
    # Otherwise somebody who keeps hammering would stay blocked forever.
    limiter, clock = make_limiter(redis_client)
    await limiter.check("user:1", limit=2, window_seconds=10)  # t=0
    clock.advance(1)
    await limiter.check("user:1", limit=2, window_seconds=10)  # t=1
    for _ in range(4):  # t=2..5, all refused
        clock.advance(1)
        assert not (await limiter.check("user:1", limit=2, window_seconds=10)).allowed

    clock.advance(5.5)  # t=10.5: the request from t=0 has left the window

    assert (await limiter.check("user:1", limit=2, window_seconds=10)).allowed


async def test_the_window_slides_with_time(redis_client: Redis) -> None:
    limiter, clock = make_limiter(redis_client)
    await limiter.check("user:1", limit=2, window_seconds=10)  # t=0
    clock.advance(5)
    await limiter.check("user:1", limit=2, window_seconds=10)  # t=5
    clock.advance(1)
    assert not (await limiter.check("user:1", limit=2, window_seconds=10)).allowed  # t=6

    clock.advance(4.1)  # t=10.1: only the t=0 request has expired
    assert (await limiter.check("user:1", limit=2, window_seconds=10)).allowed
    clock.advance(0.1)  # t=10.2: t=5 and t=10.1 are in the window
    assert not (await limiter.check("user:1", limit=2, window_seconds=10)).allowed


async def test_no_burst_across_a_minute_boundary(redis_client: Redis) -> None:
    # A fixed window would reset at the boundary and allow 10 + 10 within two
    # seconds. A sliding window still remembers the first ten.
    limiter, clock = make_limiter(redis_client)
    clock.advance(59 - clock.now % 60)  # one second before a round minute
    for _ in range(10):
        assert (await limiter.check("user:1", limit=10, window_seconds=60)).allowed

    clock.advance(2)  # just past the round minute

    assert not (await limiter.check("user:1", limit=10, window_seconds=60)).allowed


async def test_a_refusal_says_when_to_try_again(redis_client: Redis) -> None:
    limiter, clock = make_limiter(redis_client)
    await limiter.check("user:1", limit=2, window_seconds=10)  # t=0
    clock.advance(4)
    await limiter.check("user:1", limit=2, window_seconds=10)  # t=4
    clock.advance(2.5)  # t=6.5

    refused = await limiter.check("user:1", limit=2, window_seconds=10)

    # The t=0 request leaves the window at t=10, i.e. 3.5 seconds from now;
    # rounded up so that waiting that long really works.
    assert not refused.allowed
    assert refused.retry_after_seconds == 4


async def test_different_keys_do_not_affect_each_other(redis_client: Redis) -> None:
    limiter, _ = make_limiter(redis_client)
    await limiter.check("user:1", limit=1, window_seconds=60)

    assert not (await limiter.check("user:1", limit=1, window_seconds=60)).allowed
    assert (await limiter.check("user:2", limit=1, window_seconds=60)).allowed


async def test_requests_at_the_very_same_moment_are_each_counted(redis_client: Redis) -> None:
    # Twenty requests arrive together and the clock does not move, so they even
    # share the same timestamp. Exactly five may get through.
    limiter, _ = make_limiter(redis_client)

    results = await asyncio.gather(
        *(limiter.check("user:1", limit=5, window_seconds=60) for _ in range(20))
    )

    assert sum(result.allowed for result in results) == 5


async def test_idle_keys_clean_themselves_up(redis_client: Redis) -> None:
    limiter, _ = make_limiter(redis_client)

    await limiter.check("user:1", limit=5, window_seconds=60)

    ttl = await redis_client.ttl("ratelimit:user:1")
    assert 0 < ttl <= 60


async def test_a_dead_redis_lets_requests_through() -> None:
    # Fail open: protection is a bonus, the service itself must keep working.
    dead = from_url(
        "redis://localhost:1", decode_responses=True, socket_connect_timeout=0.5, socket_timeout=0.5
    )
    limiter = RateLimiter(dead)

    result = await limiter.check("user:1", limit=5, window_seconds=60)

    assert result.allowed
    await dead.aclose()
