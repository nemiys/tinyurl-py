"""POST /auth/register is limited per client IP. Needs Mongo and Redis running."""

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pymongo.asynchronous.database import AsyncDatabase

from tinyurl_py.main import app
from tinyurl_py.settings import settings

LIMIT = 3
PASSWORD = "correct horse battery staple"


@pytest.fixture(autouse=True)
def low_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "register_limit", LIMIT)


async def register(http: AsyncClient, email: str) -> int:
    response = await http.post("/auth/register", json={"email": email, "password": PASSWORD})
    return response.status_code


async def test_registrations_beyond_the_limit_get_429(http: AsyncClient) -> None:
    statuses = [await register(http, f"user{n}@example.com") for n in range(LIMIT + 2)]

    assert statuses == [201] * LIMIT + [429, 429]
    refused = await http.post(
        "/auth/register", json={"email": "late@example.com", "password": PASSWORD}
    )
    assert int(refused.headers["retry-after"]) >= 1


async def test_a_refused_registration_creates_no_account(
    http: AsyncClient, db: AsyncDatabase[dict[str, Any]]
) -> None:
    for n in range(LIMIT + 1):
        await register(http, f"user{n}@example.com")

    assert await db.users.count_documents({}) == LIMIT


async def test_failed_registrations_count_too(http: AsyncClient) -> None:
    # Probing which emails are taken must not be free either.
    statuses = [await register(http, "dana@example.com") for _ in range(LIMIT + 1)]

    assert statuses == [201] + [409] * (LIMIT - 1) + [429]


async def test_another_ip_is_not_affected(http: AsyncClient) -> None:
    for n in range(LIMIT + 1):
        await register(http, f"user{n}@example.com")

    transport = ASGITransport(app=app, client=("10.0.0.2", 5000))
    async with AsyncClient(transport=transport, base_url="http://test") as other_ip:
        assert await register(other_ip, "other@example.com") == 201


async def test_registrations_do_not_use_up_login(http: AsyncClient) -> None:
    for n in range(LIMIT + 1):
        await register(http, f"user{n}@example.com")

    response = await http.post(
        "/auth/login", json={"email": "user0@example.com", "password": PASSWORD}
    )

    assert response.status_code == 200
