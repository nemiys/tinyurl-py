"""POST /links is limited per user. Needs Mongo and Redis running."""

from typing import Any

import pytest
from httpx import AsyncClient
from pymongo.asynchronous.database import AsyncDatabase
from redis.asyncio import from_url

from tests.integration.conftest import LoggedIn
from tests.integration.test_get_link import register_other_user
from tinyurl_py.api.dependencies import get_redis
from tinyurl_py.main import app
from tinyurl_py.settings import settings

LIMIT = 3
BODY = {"url": "https://example.com/page"}


@pytest.fixture(autouse=True)
def low_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "create_link_limit", LIMIT)


async def create(http: AsyncClient, user: LoggedIn) -> int:
    return (await http.post("/links", json=BODY, headers=user.headers)).status_code


async def test_creating_beyond_the_limit_is_refused_with_429(
    http: AsyncClient, logged_in: LoggedIn, db: AsyncDatabase[dict[str, Any]]
) -> None:
    for _ in range(LIMIT):
        assert await create(http, logged_in) == 201

    refused = await http.post("/links", json=BODY, headers=logged_in.headers)

    assert refused.status_code == 429
    assert int(refused.headers["retry-after"]) >= 1  # tells the client how long to wait
    assert await db.links.count_documents({}) == LIMIT  # nothing was created


async def test_the_limit_is_per_user(http: AsyncClient, logged_in: LoggedIn) -> None:
    other = await register_other_user(http)
    for _ in range(LIMIT):
        await create(http, logged_in)

    assert await create(http, logged_in) == 429
    assert await create(http, other) == 201  # somebody else is unaffected


async def test_only_creation_is_limited(http: AsyncClient, logged_in: LoggedIn) -> None:
    for _ in range(LIMIT + 1):
        await create(http, logged_in)

    assert (await http.get("/links", headers=logged_in.headers)).status_code == 200
    assert (await http.get("/me", headers=logged_in.headers)).status_code == 200


async def test_not_logged_in_is_401_even_when_the_limit_is_used_up(
    http: AsyncClient, logged_in: LoggedIn
) -> None:
    for _ in range(LIMIT + 1):
        await create(http, logged_in)

    response = await http.post("/links", json=BODY)

    assert response.status_code == 401


async def test_creation_still_works_when_redis_is_down(
    http: AsyncClient, logged_in: LoggedIn
) -> None:
    dead = from_url(
        "redis://localhost:1", decode_responses=True, socket_connect_timeout=0.5, socket_timeout=0.5
    )
    app.dependency_overrides[get_redis] = lambda: dead

    statuses = [await create(http, logged_in) for _ in range(LIMIT + 2)]

    assert statuses == [201] * (LIMIT + 2)  # fail open: no protection, but no outage
    await dead.aclose()
