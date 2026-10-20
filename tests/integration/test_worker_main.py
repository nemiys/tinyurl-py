"""The worker as a process: `python -m tinyurl_py.worker`, run in-process here.

Connects to the real Redis (database 15) and the real Cassandra. Needs both.
"""

import asyncio
import datetime
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any

import pytest
from redis.asyncio import Redis, from_url

from tinyurl_py.events.clicks import CLICKS_STREAM, ClickEvent, publish_click
from tinyurl_py.settings import settings
from tinyurl_py.worker.__main__ import main

SELECT_DAY = "SELECT event_id FROM clicks_by_link_day WHERE link_id = %s AND day = %s"
DELETE_DAY = "DELETE FROM clicks_by_link_day WHERE link_id = %s AND day = %s"


@pytest.fixture
async def redis_db15(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Redis]:
    # main() builds its own Redis client from the settings.
    monkeypatch.setattr(settings, "redis_url", f"{settings.redis_url}/15")
    redis = from_url(settings.redis_url, decode_responses=True)
    await redis.flushdb()
    yield redis
    await redis.flushdb()
    await redis.aclose()


async def test_the_worker_starts_processes_a_click_and_shuts_down_cleanly(
    redis_db15: Redis, session: Any
) -> None:
    link_id = f"test-{uuid.uuid4()}"
    today = datetime.datetime.now(datetime.UTC).date()
    await publish_click(redis_db15, ClickEvent.new(link_id=link_id, device="mobile"))

    worker = asyncio.create_task(main())
    try:
        async with asyncio.timeout(15):
            while await redis_db15.xlen(CLICKS_STREAM) > 0:
                await asyncio.sleep(0.05)  # waiting for the worker to take the click
    finally:
        worker.cancel()  # what Ctrl-C does on Windows; main() must still clean up
        with suppress(asyncio.CancelledError):
            await worker

    rows = await asyncio.to_thread(session.execute, SELECT_DAY, (link_id, today))
    assert len(list(rows)) == 1
    await asyncio.to_thread(session.execute, DELETE_DAY, (link_id, today))
