"""Cassandra connection and the "no duplicate clicks" property of our table.

Needs the Cassandra container (and its schema, applied by `cassandra-init`)
from docker-compose.yml.
"""

import asyncio
import datetime
import uuid
from typing import Any

INSERT_CLICK = (
    "INSERT INTO clicks_by_link_day (link_id, day, clicked_at, event_id, device) "
    "VALUES (%s, %s, %s, %s, %s)"
)
COUNT_CLICKS = "SELECT count(*) FROM clicks_by_link_day WHERE link_id = %s AND day = %s"


async def test_can_connect_and_query(session: Any) -> None:
    rows = await asyncio.to_thread(session.execute, "SELECT release_version FROM system.local")

    assert rows.one() is not None


async def test_writing_the_same_click_twice_keeps_one_row(session: Any) -> None:
    # A fresh link_id per test run, so leftovers from other runs cannot interfere.
    link_id = f"test-{uuid.uuid4()}"
    now = datetime.datetime.now(datetime.UTC)
    click = (link_id, now.date(), now, uuid.uuid4(), "mobile")

    # The same event delivered twice, as at-least-once delivery may do.
    await asyncio.to_thread(session.execute, INSERT_CLICK, click)
    await asyncio.to_thread(session.execute, INSERT_CLICK, click)

    rows = await asyncio.to_thread(session.execute, COUNT_CLICKS, (link_id, now.date()))
    assert rows.one().count == 1

    await asyncio.to_thread(
        session.execute,
        "DELETE FROM clicks_by_link_day WHERE link_id = %s AND day = %s",
        (link_id, now.date()),
    )
