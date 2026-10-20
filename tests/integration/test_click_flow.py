"""The whole click pipeline, end to end:

    click on a short link -> Redis Stream -> worker -> Cassandra -> /stats

Needs Mongo, Redis and Cassandra from docker-compose.yml.
"""

from httpx import AsyncClient
from redis.asyncio import Redis

from tests.integration.conftest import TODAY, LoggedIn, MakeLink
from tinyurl_py.events.clicks import CLICKS_STREAM, ClickEvent
from tinyurl_py.persistence.click_store import ClickStore
from tinyurl_py.worker.consumer import ClickConsumer

CLICKS = 10


class CrashesAfterWriting:
    """Saves for real, then fails once on a chosen click: the worker "died" after
    the write but before acknowledging, so the message will be delivered again."""

    def __init__(self, real: ClickStore, crash_on: int) -> None:
        self._real = real
        self._crash_on = crash_on
        self._saved = 0

    async def save(self, event: ClickEvent) -> None:
        await self._real.save(event)
        self._saved += 1
        if self._saved == self._crash_on:
            raise RuntimeError("worker crashed after writing, before acknowledging")


async def drain(consumer: ClickConsumer, redis: Redis) -> None:
    while await redis.xlen(CLICKS_STREAM) > 0:
        await consumer.run_once()


async def total_clicks(web: AsyncClient, user: LoggedIn, code: str) -> int:
    response = await web.get(f"/links/{code}/stats", headers=user.headers)
    total: int = response.json()["total_clicks"]
    return total


async def test_worker_off_ten_clicks_worker_on_exactly_ten(
    stats_web: AsyncClient,
    logged_in: LoggedIn,
    make_link: MakeLink,
    redis_client: Redis,
    click_store: ClickStore,
    touched_links: list[str],
) -> None:
    code, link_id = await make_link()
    touched_links.append(link_id)

    # The worker is off: nobody reads the stream. The visitors do not notice.
    for _ in range(CLICKS):
        assert (await stats_web.get(f"/{code}")).status_code == 302
    assert await redis_client.xlen(CLICKS_STREAM) == CLICKS  # waiting in the queue
    assert await total_clicks(stats_web, logged_in, code) == 0  # not counted yet

    # The worker starts and catches up.
    worker = ClickConsumer(redis_client, click_store, "worker-1", block_ms=50)
    await worker.setup()
    await drain(worker, redis_client)

    assert await total_clicks(stats_web, logged_in, code) == CLICKS
    body = (await stats_web.get(f"/links/{code}/stats", headers=logged_in.headers)).json()
    assert body["days"][-1] == {"day": TODAY.isoformat(), "clicks": CLICKS}


async def test_a_crash_between_writing_and_acknowledging_does_not_count_a_click_twice(
    stats_web: AsyncClient,
    logged_in: LoggedIn,
    make_link: MakeLink,
    redis_client: Redis,
    click_store: ClickStore,
    touched_links: list[str],
) -> None:
    code, link_id = await make_link()
    touched_links.append(link_id)
    for _ in range(CLICKS):
        await stats_web.get(f"/{code}")

    # First run: the 4th click is written to Cassandra, then the worker "dies".
    crashing = ClickConsumer(
        redis_client, CrashesAfterWriting(click_store, crash_on=4), "worker-1", block_ms=50
    )
    await crashing.setup()
    try:
        await drain(crashing, redis_client)
    except RuntimeError:
        pass
    assert await redis_client.xlen(CLICKS_STREAM) == CLICKS - 3  # 4th was never acknowledged

    # The worker comes back (same name) and the 4th click is delivered again.
    restarted = ClickConsumer(redis_client, click_store, "worker-1", block_ms=50)
    await restarted.setup()
    await drain(restarted, redis_client)

    assert await total_clicks(stats_web, logged_in, code) == CLICKS  # not 11
