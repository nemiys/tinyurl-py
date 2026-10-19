"""Fixtures shared by the API integration tests.

They need the Mongo container from docker-compose.yml running. Everything
happens in a separate `tinyurl_test` database that is wiped around each test.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pymongo.asynchronous.database import AsyncDatabase
from redis.asyncio import Redis, from_url

from tinyurl_py.api.dependencies import get_db, get_redis
from tinyurl_py.main import app
from tinyurl_py.persistence.mongo import create_client, ensure_indexes
from tinyurl_py.settings import settings

TEST_DATABASE = "tinyurl_test"


@pytest.fixture
async def db() -> AsyncIterator[AsyncDatabase[dict[str, Any]]]:
    client = create_client()
    await client.drop_database(TEST_DATABASE)
    database = client[TEST_DATABASE]
    await ensure_indexes(database)
    yield database
    await client.drop_database(TEST_DATABASE)
    await client.close()


@pytest.fixture
async def http(db: AsyncDatabase[dict[str, Any]]) -> AsyncIterator[AsyncClient]:
    # Swap the real database for the test one, only for the duration of a test.
    app.dependency_overrides[get_db] = lambda: db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@dataclass
class LoggedIn:
    user_id: str
    headers: dict[str, str]  # pass as `headers=` to act as this user


@pytest.fixture
async def logged_in(http: AsyncClient) -> LoggedIn:
    """A freshly registered and logged-in user."""
    credentials = {"email": "dana@example.com", "password": "correct horse battery staple"}
    registered = await http.post("/auth/register", json=credentials)
    login = await http.post("/auth/login", json=credentials)
    token = login.json()["access_token"]
    return LoggedIn(user_id=registered.json()["id"], headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
    # Redis database 15 is only for tests; wiped before and after each one.
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
