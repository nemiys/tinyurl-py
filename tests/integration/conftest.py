"""Fixtures shared by the API integration tests.

They need the Mongo container from docker-compose.yml running. Everything
happens in a separate `tinyurl_test` database that is wiped around each test.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pymongo.asynchronous.database import AsyncDatabase

from tinyurl_py.api.dependencies import get_db
from tinyurl_py.main import app
from tinyurl_py.persistence.mongo import create_client, ensure_indexes

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
