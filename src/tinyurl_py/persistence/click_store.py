"""Writing click events to Cassandra (table `clicks_by_link_day`)."""

import asyncio
from datetime import UTC
from typing import Any, Self

from tinyurl_py.events.clicks import ClickEvent

# `?` marks a value that is sent separately from the query text. Cassandra
# parses this query once (see `create`), and values can never be mistaken for
# query code.
INSERT_CLICK = (
    "INSERT INTO clicks_by_link_day (link_id, day, clicked_at, event_id, device) "
    "VALUES (?, ?, ?, ?, ?)"
)


class ClickStore:
    def __init__(self, session: Any, insert: Any) -> None:
        self._session = session
        self._insert = insert

    @classmethod
    async def create(cls, session: Any) -> Self:
        # Preparing is a blocking call to the server, hence the helper thread.
        insert = await asyncio.to_thread(session.prepare, INSERT_CLICK)
        return cls(session, insert)

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
