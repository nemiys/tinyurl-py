"""/ready answers "can the app do real work?", i.e. is Mongo reachable.

Needs the Mongo container from docker-compose.yml running.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient

from tinyurl_py.main import app
from tinyurl_py.settings import settings


@asynccontextmanager
async def running_app() -> AsyncIterator[AsyncClient]:
    # httpx's ASGITransport does not run the app's startup/shutdown code, so
    # we run it ourselves: the lifespan is where the Mongo client gets created.
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def test_ready_when_mongo_is_up() -> None:
    async with running_app() as client:
        response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_not_ready_when_mongo_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    # Port 1 has nothing listening, so Mongo is "down" for this one test.
    monkeypatch.setattr(settings, "mongo_url", "mongodb://localhost:1")

    async with running_app() as client:
        response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
