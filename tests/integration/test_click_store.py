"""Writing click events to Cassandra. Needs the Cassandra container (and its
schema, applied by `cassandra-init`) from docker-compose.yml."""

import asyncio
import datetime
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest

from tinyurl_py.events.clicks import ClickEvent
from tinyurl_py.persistence.click_store import ClickStore

SELECT_DAY = (
    "SELECT clicked_at, event_id, device FROM clicks_by_link_day WHERE link_id = %s AND day = %s"
)
DELETE_DAY = "DELETE FROM clicks_by_link_day WHERE link_id = %s AND day = %s"
DAYS_USED = [datetime.date(2026, 1, 1), datetime.date(2026, 1, 2)]


@pytest.fixture
def link_id() -> str:
    # Fresh per test, so leftovers from other runs cannot interfere.
    return f"test-{uuid.uuid4()}"


@pytest.fixture
async def store(session: Any, link_id: str) -> AsyncIterator[ClickStore]:
    yield await ClickStore.create(session)
    for day in DAYS_USED:
        await asyncio.to_thread(session.execute, DELETE_DAY, (link_id, day))


def click(link_id: str, at: datetime.datetime, device: str = "desktop") -> ClickEvent:
    return ClickEvent.model_validate(
        {"event_id": uuid.uuid4(), "link_id": link_id, "clicked_at": at, "device": device}
    )


def at(day: int, hour: int = 12, minute: int = 0) -> datetime.datetime:
    return datetime.datetime(2026, 1, day, hour, minute, tzinfo=datetime.UTC)


async def rows_of(session: Any, link_id: str, day: datetime.date) -> list[Any]:
    result = await asyncio.to_thread(session.execute, SELECT_DAY, (link_id, day))
    return list(result)


async def test_a_saved_click_can_be_read_back(
    session: Any, store: ClickStore, link_id: str
) -> None:
    event = click(link_id, at(1), device="mobile")

    await store.save(event)

    [row] = await rows_of(session, link_id, datetime.date(2026, 1, 1))
    assert row.event_id == event.event_id
    assert row.device == "mobile"
    assert row.clicked_at == event.clicked_at.replace(tzinfo=None)  # Cassandra returns UTC, naive


async def test_saving_the_same_event_twice_keeps_one_row(
    session: Any, store: ClickStore, link_id: str
) -> None:
    event = click(link_id, at(1))

    await store.save(event)
    await store.save(event)  # as a redelivered message would

    assert len(await rows_of(session, link_id, datetime.date(2026, 1, 1))) == 1


async def test_different_events_are_different_rows(
    session: Any, store: ClickStore, link_id: str
) -> None:
    await store.save(click(link_id, at(1, minute=0)))
    await store.save(click(link_id, at(1, minute=0)))  # same moment, different event_id

    assert len(await rows_of(session, link_id, datetime.date(2026, 1, 1))) == 2


async def test_the_day_is_taken_from_the_click_time_in_utc(
    session: Any, store: ClickStore, link_id: str
) -> None:
    await store.save(click(link_id, at(1, hour=23, minute=59)))
    await store.save(click(link_id, at(2, hour=0, minute=1)))

    assert len(await rows_of(session, link_id, datetime.date(2026, 1, 1))) == 1
    assert len(await rows_of(session, link_id, datetime.date(2026, 1, 2))) == 1


async def test_a_failed_write_is_not_swallowed() -> None:
    # The worker must see the failure, otherwise it would acknowledge the
    # message and the click would be lost for good.
    class BrokenSession:
        def prepare(self, query: str) -> str:
            return query

        def execute(self, statement: str, values: Any) -> None:
            raise RuntimeError("cassandra is down")

    store = await ClickStore.create(BrokenSession())

    with pytest.raises(RuntimeError):
        await store.save(click("abc", at(1)))


async def test_clicks_are_counted_per_day(store: ClickStore, link_id: str) -> None:
    for _ in range(3):
        await store.save(click(link_id, at(1)))
    await store.save(click(link_id, at(2)))

    counts = await store.count_per_day(link_id, [datetime.date(2026, 1, d) for d in (1, 2, 3)])

    assert counts == [3, 1, 0]  # same order as the days asked for; an empty day is 0


async def test_counting_no_days_is_empty(store: ClickStore, link_id: str) -> None:
    assert await store.count_per_day(link_id, []) == []
