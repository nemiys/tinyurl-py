"""POST /auth/register against a real Mongo (separate `tinyurl_test` database).

Needs the Mongo container from docker-compose.yml running.
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
PASSWORD = "correct horse battery staple"


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


async def test_registering_creates_a_user_without_leaking_secrets(http: AsyncClient) -> None:
    response = await http.post(
        "/auth/register", json={"email": "dana@example.com", "password": PASSWORD}
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "email", "created_at"}
    assert body["email"] == "dana@example.com"


async def test_only_a_password_hash_is_stored(
    http: AsyncClient, db: AsyncDatabase[dict[str, Any]]
) -> None:
    await http.post("/auth/register", json={"email": "dana@example.com", "password": PASSWORD})

    stored = await db.users.find_one({"email": "dana@example.com"})

    assert stored is not None
    assert stored["password_hash"].startswith("$argon2")
    assert PASSWORD not in str(stored)


async def test_second_registration_with_same_email_is_a_conflict(http: AsyncClient) -> None:
    first = await http.post(
        "/auth/register", json={"email": "dana@example.com", "password": PASSWORD}
    )
    # Same person, different capitalisation: must still count as the same email.
    second = await http.post(
        "/auth/register", json={"email": "Dana@Example.com", "password": PASSWORD}
    )

    assert first.status_code == 201
    assert second.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": PASSWORD},
        {"email": "dana@example.com", "password": "short"},
        {"email": "dana@example.com"},
    ],
)
async def test_invalid_registration_is_rejected(http: AsyncClient, payload: dict[str, str]) -> None:
    response = await http.post("/auth/register", json=payload)

    assert response.status_code == 422
