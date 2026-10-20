"""Every successful redirect publishes a click event to a Redis Stream.

Needs the Mongo and Redis containers from docker-compose.yml running.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from bson import ObjectId
from httpx import AsyncClient
from pymongo.asynchronous.database import AsyncDatabase
from redis.asyncio import Redis, from_url

from tests.integration.conftest import LoggedIn
from tests.integration.test_redirect import DESKTOP, PHONE
from tinyurl_py.events.clicks import CLICKS_STREAM, ClickEvent, publish_click


async def create_link(web: AsyncClient, user: LoggedIn) -> str:
    response = await web.post("/links", json={"url": "https://example.com/p"}, headers=user.headers)
    code: str = response.json()["code"]
    return code


async def published_events(redis_client: Redis) -> list[ClickEvent]:
    # redis-py's type hints for streams are loose, hence the explicit Any.
    entries: Any = await redis_client.xrange(CLICKS_STREAM)
    return [ClickEvent.model_validate_json(fields["data"]) for _, fields in entries]


async def test_a_click_publishes_one_event(
    web: AsyncClient,
    logged_in: LoggedIn,
    redis_client: Redis,
    db: AsyncDatabase[dict[str, Any]],
) -> None:
    code = await create_link(web, logged_in)
    link = await db.links.find_one({"code": code})
    assert link is not None

    await web.get(f"/{code}", headers={"User-Agent": DESKTOP})

    [event] = await published_events(redis_client)
    assert event.link_id == str(link["_id"])  # the link's identity, not its public code
    assert event.device == "desktop"
    assert datetime.now(UTC) - event.clicked_at < timedelta(seconds=10)


@pytest.mark.parametrize(("user_agent", "device"), [(PHONE, "mobile"), (DESKTOP, "desktop")])
async def test_the_device_is_recorded(
    web: AsyncClient, logged_in: LoggedIn, redis_client: Redis, user_agent: str, device: str
) -> None:
    code = await create_link(web, logged_in)

    await web.get(f"/{code}", headers={"User-Agent": user_agent})

    [event] = await published_events(redis_client)
    assert event.device == device


async def test_every_click_is_its_own_event_even_when_served_from_the_cache(
    web: AsyncClient, logged_in: LoggedIn, redis_client: Redis
) -> None:
    code = await create_link(web, logged_in)

    await web.get(f"/{code}")  # first click: cache miss, filled from Mongo
    await web.get(f"/{code}")  # second click: served from the cache

    first, second = await published_events(redis_client)
    assert first.event_id != second.event_id  # a repeat of the SAME event shares its id
    assert first.link_id == second.link_id


async def test_unknown_and_expired_links_publish_nothing(
    web: AsyncClient, redis_client: Redis, db: AsyncDatabase[dict[str, Any]]
) -> None:
    now = datetime.now(UTC)
    await db.links.insert_one(
        {
            "code": "Expired",
            "owner_id": ObjectId(),
            "url": "https://example.com/",
            "mobile_url": None,
            "expires_at": now - timedelta(hours=1),
            "created_at": now - timedelta(days=1),
        }
    )

    await web.get("/Missing")
    await web.get("/Expired")

    assert await published_events(redis_client) == []


async def test_publishing_never_raises_when_redis_is_down() -> None:
    dead = from_url(
        "redis://localhost:1", decode_responses=True, socket_connect_timeout=0.5, socket_timeout=0.5
    )
    event = ClickEvent.new(link_id="abc", device="desktop")

    await publish_click(dead, event)  # a lost click is logged, never an error
    await dead.aclose()
