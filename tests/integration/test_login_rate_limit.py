"""POST /auth/login is limited per client IP. Needs Mongo and Redis running."""

import pytest
from httpx import ASGITransport, AsyncClient

from tinyurl_py.main import app
from tinyurl_py.settings import settings

LIMIT = 3
EMAIL = "dana@example.com"
PASSWORD = "correct horse battery staple"


@pytest.fixture(autouse=True)
def low_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "login_limit", LIMIT)


async def attempt(http: AsyncClient, password: str) -> int:
    response = await http.post("/auth/login", json={"email": EMAIL, "password": password})
    return response.status_code


async def test_attempts_beyond_the_limit_get_429(http: AsyncClient) -> None:
    await http.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})

    statuses = [await attempt(http, f"wrong password {n}") for n in range(LIMIT + 2)]

    assert statuses == [401] * LIMIT + [429, 429]
    refused = await http.post("/auth/login", json={"email": EMAIL, "password": "x" * 10})
    assert int(refused.headers["retry-after"]) >= 1


async def test_once_blocked_even_the_right_password_is_refused(http: AsyncClient) -> None:
    await http.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})
    for n in range(LIMIT):
        await attempt(http, f"wrong password {n}")

    # A guesser must not get to learn whether the next guess was the right one.
    assert await attempt(http, PASSWORD) == 429


async def test_successful_logins_count_too(http: AsyncClient) -> None:
    await http.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})

    statuses = [await attempt(http, PASSWORD) for _ in range(LIMIT + 1)]

    assert statuses == [200] * LIMIT + [429]


async def test_another_ip_is_not_affected(http: AsyncClient) -> None:
    await http.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})
    for n in range(LIMIT + 1):
        await attempt(http, f"wrong password {n}")

    transport = ASGITransport(app=app, client=("10.0.0.2", 5000))
    async with AsyncClient(transport=transport, base_url="http://test") as other_ip:
        assert await attempt(other_ip, PASSWORD) == 200


async def test_login_attempts_do_not_use_up_registration(http: AsyncClient) -> None:
    for n in range(LIMIT + 2):
        await attempt(http, f"wrong password {n}")  # uses up the login allowance

    response = await http.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})

    assert response.status_code == 201
