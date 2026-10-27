"""HEAD /{code}: what link checkers and preview bots send to see where a link
leads. Answered like GET, but never counted as a click.

Needs the Mongo and Redis containers from docker-compose.yml running.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from bson import ObjectId
from httpx import AsyncClient
from pymongo.asynchronous.database import AsyncDatabase
from redis.asyncio import Redis

from tests.integration.conftest import LoggedIn
from tests.integration.test_redirect import PHONE, create_link
from tinyurl_py.events.clicks import CLICKS_STREAM
from tinyurl_py.settings import settings


async def test_head_answers_like_get(web: AsyncClient, logged_in: LoggedIn) -> None:
    code = await create_link(web, logged_in)

    response = await web.head(f"/{code}")

    assert response.status_code == 302
    assert response.headers["location"] == "https://example.com/page"
    assert response.headers["cache-control"] == "no-store"


async def test_head_sends_phones_to_the_mobile_url(web: AsyncClient, logged_in: LoggedIn) -> None:
    code = await create_link(web, logged_in, mobile_url="https://m.example.com/page")

    response = await web.head(f"/{code}", headers={"User-Agent": PHONE})

    assert response.headers["location"] == "https://m.example.com/page"


async def test_head_is_not_counted_as_a_click(
    web: AsyncClient, logged_in: LoggedIn, redis_client: Redis
) -> None:
    code = await create_link(web, logged_in)

    await web.head(f"/{code}")

    # A chat app previewing a pasted link must not inflate its statistics.
    assert await redis_client.xlen(CLICKS_STREAM) == 0


async def test_head_on_an_unknown_code_is_404(web: AsyncClient) -> None:
    assert (await web.head("/Unknown")).status_code == 404


async def test_head_on_an_expired_link_is_410(
    web: AsyncClient, db: AsyncDatabase[dict[str, Any]]
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
            "deleted_at": None,
        }
    )

    assert (await web.head("/Expired")).status_code == 410


async def test_head_counts_toward_the_redirect_limit(
    web: AsyncClient, logged_in: LoggedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "redirect_limit", 2)
    code = await create_link(web, logged_in)

    # Otherwise HEAD would be a side door for guessing codes without a limit.
    await web.head(f"/{code}")
    await web.head(f"/{code}")

    assert (await web.get(f"/{code}")).status_code == 429
