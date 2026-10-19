"""GET /{code}: the redirect, against real Mongo and Redis (see conftest.py).

Needs the Mongo and Redis containers from docker-compose.yml running.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from bson import ObjectId
from httpx import AsyncClient
from pymongo.asynchronous.database import AsyncDatabase
from redis.asyncio import Redis, from_url

from tests.integration.conftest import LoggedIn
from tinyurl_py.api.dependencies import get_redis
from tinyurl_py.main import app
from tinyurl_py.settings import settings

PHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148 Safari/604.1"
DESKTOP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36"


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
    client = from_url(settings.redis_url, db=15, decode_responses=True)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def web(http: AsyncClient, redis_client: Redis) -> AsyncClient:
    """The test client, with the test Redis plugged in too."""
    app.dependency_overrides[get_redis] = lambda: redis_client
    return http


async def create_link(web: AsyncClient, user: LoggedIn, **fields: str) -> str:
    body = {"url": "https://example.com/page", **fields}
    response = await web.post("/links", json=body, headers=user.headers)
    code: str = response.json()["code"]
    return code


async def test_a_created_link_redirects_to_its_url(web: AsyncClient, logged_in: LoggedIn) -> None:
    code = await create_link(web, logged_in)

    response = await web.get(f"/{code}")

    assert response.status_code == 302
    assert response.headers["location"] == "https://example.com/page"
    assert response.headers["cache-control"] == "no-store"  # browsers must come back to us


async def test_first_visit_fills_the_cache(
    web: AsyncClient, logged_in: LoggedIn, redis_client: Redis
) -> None:
    code = await create_link(web, logged_in)

    await web.get(f"/{code}")

    assert await redis_client.exists(f"link:{code}") == 1


async def test_second_visit_is_served_from_the_cache(
    web: AsyncClient, logged_in: LoggedIn, db: AsyncDatabase[dict[str, Any]]
) -> None:
    code = await create_link(web, logged_in)
    await web.get(f"/{code}")
    await db.links.delete_many({})  # Mongo no longer knows the link...

    response = await web.get(f"/{code}")

    assert response.status_code == 302  # ...yet the redirect still works


async def test_unknown_code_is_not_found(web: AsyncClient) -> None:
    response = await web.get("/Missing")

    assert response.status_code == 404


@pytest.mark.parametrize("path", ["/favicon.ico", "/wp-login.php", "/short", "/waytoolong"])
async def test_paths_that_cannot_be_codes_are_rejected_before_any_lookup(
    web: AsyncClient, redis_client: Redis, path: str
) -> None:
    response = await web.get(path)

    assert response.status_code == 404
    assert await redis_client.keys("*") == []


async def test_expired_link_is_gone(web: AsyncClient, db: AsyncDatabase[dict[str, Any]]) -> None:
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

    response = await web.get("/Expired")

    assert response.status_code == 410


@pytest.mark.parametrize(
    ("user_agent", "expected"),
    [
        (PHONE, "https://m.example.com/page"),
        (DESKTOP, "https://example.com/page"),
    ],
)
async def test_phones_are_sent_to_the_mobile_url(
    web: AsyncClient, logged_in: LoggedIn, user_agent: str, expected: str
) -> None:
    code = await create_link(web, logged_in, mobile_url="https://m.example.com/page")

    response = await web.get(f"/{code}", headers={"User-Agent": user_agent})

    assert response.headers["location"] == expected


async def test_phone_without_a_mobile_url_gets_the_normal_one(
    web: AsyncClient, logged_in: LoggedIn
) -> None:
    code = await create_link(web, logged_in)

    response = await web.get(f"/{code}", headers={"User-Agent": PHONE})

    assert response.headers["location"] == "https://example.com/page"


async def test_redirect_still_works_when_redis_is_down(
    web: AsyncClient, logged_in: LoggedIn
) -> None:
    code = await create_link(web, logged_in)
    dead = from_url(
        "redis://localhost:1", decode_responses=True, socket_connect_timeout=0.5, socket_timeout=0.5
    )
    app.dependency_overrides[get_redis] = lambda: dead

    response = await web.get(f"/{code}")

    assert response.status_code == 302
    await dead.aclose()


async def test_the_catch_all_does_not_swallow_the_other_routes(web: AsyncClient) -> None:
    assert (await web.get("/health")).status_code == 200
    assert (await web.get("/docs")).status_code == 200
    assert (await web.get("/me")).status_code == 401  # reached the real /me
