"""The real application, started the way uvicorn starts it: its own lifespan, its
own Mongo / Redis / Cassandra connections, and NO dependency overrides.

Every other test swaps those connections for test ones; this is the one that
proves the wiring itself works. It still uses the test Mongo database and Redis
database 15, so it never touches the data of a normal local run.
"""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis, from_url

from tests.integration.conftest import TEST_DATABASE
from tinyurl_py.events.clicks import CLICKS_STREAM
from tinyurl_py.main import app
from tinyurl_py.persistence.mongo import create_client
from tinyurl_py.settings import settings


@pytest.fixture
async def redis_db15(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Redis]:
    monkeypatch.setattr(settings, "redis_url", f"{settings.redis_url}/15")
    redis = from_url(settings.redis_url, decode_responses=True)
    await redis.flushdb()
    yield redis
    await redis.flushdb()
    await redis.aclose()


@pytest.fixture
async def running_app(
    monkeypatch: pytest.MonkeyPatch, redis_db15: Redis
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(settings, "mongo_database", TEST_DATABASE)
    app.dependency_overrides.clear()
    mongo = create_client()
    await mongo.drop_database(TEST_DATABASE)

    async with app.router.lifespan_context(app):  # startup now, shutdown on exit
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client

    await mongo.drop_database(TEST_DATABASE)
    await mongo.close()


async def test_a_user_can_go_through_the_whole_journey(
    running_app: AsyncClient, redis_db15: Redis
) -> None:
    credentials = {"email": "dana@example.com", "password": "correct horse battery staple"}
    assert (await running_app.post("/auth/register", json=credentials)).status_code == 201
    token = (await running_app.post("/auth/login", json=credentials)).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    created = await running_app.post("/links", json={"url": "https://example.com/p"}, headers=auth)
    code = created.json()["code"]
    assert created.status_code == 201

    redirect = await running_app.get(f"/{code}")
    assert redirect.status_code == 302
    assert redirect.headers["location"] == "https://example.com/p"
    assert await redis_db15.xlen(CLICKS_STREAM) == 1  # the click is waiting for the worker

    listing = (await running_app.get("/links", headers=auth)).json()
    assert [item["code"] for item in listing["items"]] == [code]

    # The first call that needs Cassandra connects to it.
    stats = await running_app.get(f"/links/{code}/stats", headers=auth)
    assert stats.status_code == 200
    assert stats.json()["total_clicks"] == 0  # no worker ran, so not counted yet

    assert (await running_app.delete(f"/links/{code}", headers=auth)).status_code == 204
    assert (await running_app.get(f"/{code}")).status_code == 404
    assert (await running_app.get("/health")).json() == {"status": "ok"}
    assert (await running_app.get("/ready")).json() == {"status": "ready"}
