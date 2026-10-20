"""Writing click events to Cassandra (table `clicks_by_link_day`)."""

import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, date
from typing import Any, Self

from tinyurl_py.events.clicks import ClickEvent
from tinyurl_py.persistence import cassandra

logger = logging.getLogger(__name__)

# `?` marks a value that is sent separately from the query text. Cassandra
# parses this query once (see `create`), and values can never be mistaken for
# query code.
INSERT_CLICK = (
    "INSERT INTO clicks_by_link_day (link_id, day, clicked_at, event_id, device) "
    "VALUES (?, ?, ?, ?, ?)"
)
COUNT_CLICKS = "SELECT count(*) FROM clicks_by_link_day WHERE link_id = ? AND day = ?"

# How many days are counted at the same time. Each count is a separate query
# on its own partition; a few in parallel is fast without flooding the server.
MAX_PARALLEL_COUNTS = 8


class ClickStore:
    def __init__(self, session: Any, insert: Any, count: Any) -> None:
        self._session = session
        self._insert = insert
        self._count = count

    @classmethod
    async def create(cls, session: Any) -> Self:
        # Preparing is a blocking call to the server, hence the helper thread.
        insert = await asyncio.to_thread(session.prepare, INSERT_CLICK)
        count = await asyncio.to_thread(session.prepare, COUNT_CLICKS)
        return cls(session, insert, count)

    async def save(self, event: ClickEvent) -> None:
        """Write one click. The primary key is made of fields that all come
        from the event itself, so saving the same event twice overwrites the
        same row instead of adding another one.

        Errors are deliberately not caught: the caller (the worker) must know
        the write failed, so that it does not acknowledge the message.
        """
        clicked_at = event.clicked_at
        # The partition key holds the day, always in UTC so that a click lands
        # on the same day no matter where the server runs.
        day = clicked_at.astimezone(UTC).date()
        values = (event.link_id, day, clicked_at, event.event_id, event.device)
        await asyncio.to_thread(self._session.execute, self._insert, values)

    async def count_per_day(self, link_id: str, days: Sequence[date]) -> list[int]:
        """Clicks of one link on each of the given days, in the same order.

        One query per day, because a day is exactly one partition: a read that
        touches a single partition is what Cassandra does best. Counting rows
        (instead of keeping a "+1" counter) means a click that was delivered
        twice is still one row, and so still one click.
        """
        gate = asyncio.Semaphore(MAX_PARALLEL_COUNTS)

        async def count_day(day: date) -> int:
            async with gate:
                rows = await asyncio.to_thread(self._session.execute, self._count, (link_id, day))
                return int(rows.one().count)

        return list(await asyncio.gather(*(count_day(day) for day in days)))


class ClickStoreUnavailable(Exception):
    """Cassandra could not be reached."""


class LazyClickStore:
    """Connects to Cassandra the first time somebody needs it.

    The API only needs Cassandra for statistics. If it connected at startup, a
    Cassandra that is down or still booting would keep redirects from working
    too. So: connect on first use, keep the connection, and when Cassandra is
    unreachable fail only that request and try again on the next one.
    """

    def __init__(self) -> None:
        self._store: ClickStore | None = None
        self._session: Any = None
        # Two requests arriving together must not both open a connection.
        self._lock = asyncio.Lock()

    async def get(self) -> ClickStore:
        if self._store is None:
            async with self._lock:
                if self._store is None:  # someone may have connected while we waited
                    self._store = await self._open()
        return self._store

    async def _open(self) -> ClickStore:
        session = None
        try:
            session = await cassandra.connect()
            store = await ClickStore.create(session)
        except Exception as error:
            if session is not None:
                await cassandra.close(session)
            logger.warning("Could not reach Cassandra: %s", error)
            raise ClickStoreUnavailable from error
        self._session = session
        return store

    async def close(self) -> None:
        if self._session is not None:
            await cassandra.close(self._session)
        self._store = None
        self._session = None
