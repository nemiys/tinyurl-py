"""The worker's consumer: Redis Stream in, store out.

Needs the Redis container (and, for the end-to-end test, Cassandra) from
docker-compose.yml. Most tests use a fake store so that failures can be staged.
"""

import asyncio
import datetime
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from redis.asyncio import Redis

from tinyurl_py.events.clicks import CLICKS_STREAM, ClickEvent, publish_click
from tinyurl_py.persistence.cassandra import close, connect
from tinyurl_py.persistence.click_store import ClickStore
from tinyurl_py.worker.consumer import GROUP, ClickConsumer


class FakeStore:
    """Remembers what it was asked to save; can be told to fail."""

    def __init__(self, *, failures: int = 0) -> None:
        self.saved: list[ClickEvent] = []
        self.failures = failures  # how many saves fail before it starts working

    async def save(self, event: ClickEvent) -> None:
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("cassandra is down")
        self.saved.append(event)


def new_event(link_id: str = "link-1") -> ClickEvent:
    return ClickEvent.new(link_id=link_id, device="desktop")


async def make_consumer(
    redis: Redis, store: Any, name: str = "worker-1", **options: Any
) -> ClickConsumer:
    consumer = ClickConsumer(redis, store, name, block_ms=50, retry_delay_s=0.01, **options)
    await consumer.setup()
    return consumer


async def stream_length(redis: Redis) -> int:
    length: int = await redis.xlen(CLICKS_STREAM)
    return length


async def pending_count(redis: Redis) -> int:
    summary: Any = await redis.xpending(CLICKS_STREAM, GROUP)
    count: int = summary["pending"]
    return count


async def test_a_handled_event_is_saved_acknowledged_and_removed(redis_client: Redis) -> None:
    store = FakeStore()
    consumer = await make_consumer(redis_client, store)
    event = new_event()
    await publish_click(redis_client, event)

    handled = await consumer.run_once()

    assert handled == 1
    assert store.saved == [event]
    assert await pending_count(redis_client) == 0  # acknowledged
    assert await stream_length(redis_client) == 0  # and deleted, so the stream stays small


async def test_setup_can_run_twice(redis_client: Redis) -> None:
    consumer = await make_consumer(redis_client, FakeStore())

    await consumer.setup()  # the group already exists; that is fine


async def test_events_published_before_the_worker_ever_started_are_not_lost(
    redis_client: Redis,
) -> None:
    store = FakeStore()
    await publish_click(redis_client, new_event())  # nobody is listening yet
    consumer = await make_consumer(redis_client, store)

    await consumer.run_once()

    assert len(store.saved) == 1


async def test_a_failed_save_leaves_the_message_waiting_not_lost(redis_client: Redis) -> None:
    store = FakeStore(failures=1)
    consumer = await make_consumer(redis_client, store)
    await publish_click(redis_client, new_event())

    with pytest.raises(RuntimeError):
        await consumer.run_once()

    assert store.saved == []
    assert await pending_count(redis_client) == 1  # delivered but never acknowledged
    assert await stream_length(redis_client) == 1


async def test_a_restarted_worker_finishes_what_it_left_unfinished(redis_client: Redis) -> None:
    crashed = await make_consumer(redis_client, FakeStore(failures=1), name="worker-1")
    await publish_click(redis_client, new_event())
    with pytest.raises(RuntimeError):
        await crashed.run_once()

    store = FakeStore()
    restarted = await make_consumer(redis_client, store, name="worker-1")  # same name
    await restarted.run_once()

    assert len(store.saved) == 1
    assert await pending_count(redis_client) == 0


async def test_another_worker_takes_over_a_message_that_has_waited_too_long(
    redis_client: Redis,
) -> None:
    dead = await make_consumer(redis_client, FakeStore(failures=1), name="worker-1")
    await publish_click(redis_client, new_event())
    with pytest.raises(RuntimeError):
        await dead.run_once()  # worker-1 never comes back

    store = FakeStore()
    other = await make_consumer(redis_client, store, name="worker-2", claim_idle_ms=0)
    await other.run_once()

    assert len(store.saved) == 1
    assert await pending_count(redis_client) == 0


async def test_a_recent_message_is_left_to_the_worker_that_holds_it(redis_client: Redis) -> None:
    busy = await make_consumer(redis_client, FakeStore(failures=1), name="worker-1")
    await publish_click(redis_client, new_event())
    with pytest.raises(RuntimeError):
        await busy.run_once()

    store = FakeStore()
    other = await make_consumer(redis_client, store, name="worker-2", claim_idle_ms=60_000)
    await other.run_once()

    assert store.saved == []  # worker-1 may just be slow; do not steal
    assert await pending_count(redis_client) == 1


@pytest.mark.parametrize("fields", [{"data": "{not json"}, {"unexpected": "field"}])
async def test_an_unreadable_message_is_dropped_instead_of_blocking_the_queue(
    redis_client: Redis, fields: dict[str, str]
) -> None:
    store = FakeStore()
    consumer = await make_consumer(redis_client, store)
    await redis_client.xadd(CLICKS_STREAM, fields)  # type: ignore[arg-type]
    await publish_click(redis_client, new_event())  # a good one right behind it

    await consumer.run_once()

    assert len(store.saved) == 1  # the good one got through
    assert await pending_count(redis_client) == 0
    assert await stream_length(redis_client) == 0


async def test_more_events_than_one_batch_are_all_handled(redis_client: Redis) -> None:
    store = FakeStore()
    consumer = await make_consumer(redis_client, store, batch_size=10)
    for _ in range(25):
        await publish_click(redis_client, new_event())

    while await stream_length(redis_client) > 0:
        await consumer.run_once()

    assert len(store.saved) == 25
    assert len({event.event_id for event in store.saved}) == 25


async def test_run_keeps_going_after_a_failure_and_stops_when_asked(redis_client: Redis) -> None:
    store = FakeStore(failures=2)
    consumer = await make_consumer(redis_client, store)
    await publish_click(redis_client, new_event())
    stop = asyncio.Event()

    task = asyncio.create_task(consumer.run(stop))
    async with asyncio.timeout(5):
        while not store.saved:
            await asyncio.sleep(0.02)  # it retried through both failures
    stop.set()
    async with asyncio.timeout(2):
        await task  # and it exits cleanly


# End to end, with the real Cassandra.

SELECT_DAY = "SELECT event_id FROM clicks_by_link_day WHERE link_id = %s AND day = %s"
DELETE_DAY = "DELETE FROM clicks_by_link_day WHERE link_id = %s AND day = %s"


@pytest.fixture
async def session() -> AsyncIterator[Any]:
    session = await connect()
    yield session
    await close(session)


async def test_clicks_reach_cassandra_and_a_duplicate_is_not_counted_twice(
    redis_client: Redis, session: Any
) -> None:
    link_id = f"test-{uuid.uuid4()}"
    today = datetime.datetime.now(datetime.UTC).date()
    store = await ClickStore.create(session)
    consumer = await make_consumer(redis_client, store)
    duplicated = new_event(link_id)
    await publish_click(redis_client, duplicated)
    await publish_click(redis_client, duplicated)  # delivered twice, as at-least-once may do
    await publish_click(redis_client, new_event(link_id))

    while await stream_length(redis_client) > 0:
        await consumer.run_once()

    rows = await asyncio.to_thread(session.execute, SELECT_DAY, (link_id, today))
    assert len(list(rows)) == 2  # three messages, two distinct clicks
    await asyncio.to_thread(session.execute, DELETE_DAY, (link_id, today))
