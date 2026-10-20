"""GET /{code} is limited per client IP. Needs Mongo and Redis running."""

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis

from tests.integration.conftest import LoggedIn
from tinyurl_py.events.clicks import CLICKS_STREAM
from tinyurl_py.main import app
from tinyurl_py.settings import settings

LIMIT = 3


@pytest.fixture(autouse=True)
def low_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "redirect_limit", LIMIT)


async def make_code(http: AsyncClient, user: LoggedIn) -> str:
    response = await http.post(
        "/links", json={"url": "https://example.com/p"}, headers=user.headers
    )
    code: str = response.json()["code"]
    return code


async def test_requests_beyond_the_limit_get_429(http: AsyncClient, logged_in: LoggedIn) -> None:
    code = await make_code(http, logged_in)

    statuses = [(await http.get(f"/{code}")).status_code for _ in range(LIMIT + 2)]

    assert statuses == [302] * LIMIT + [429, 429]
    refused = await http.get(f"/{code}")
    assert int(refused.headers["retry-after"]) >= 1


async def test_a_refused_request_is_not_counted_as_a_click(
    http: AsyncClient, logged_in: LoggedIn, redis_client: Redis
) -> None:
    code = await make_code(http, logged_in)

    for _ in range(LIMIT + 3):
        await http.get(f"/{code}")

    assert await redis_client.xlen(CLICKS_STREAM) == LIMIT


async def test_the_limit_is_per_ip(http: AsyncClient, logged_in: LoggedIn) -> None:
    code = await make_code(http, logged_in)
    for _ in range(LIMIT + 1):
        await http.get(f"/{code}")  # this client's IP is used up

    transport = ASGITransport(app=app, client=("10.0.0.2", 5000))  # somebody else
    async with AsyncClient(transport=transport, base_url="http://test") as other_ip:
        assert (await other_ip.get(f"/{code}")).status_code == 302
    assert (await http.get(f"/{code}")).status_code == 429


async def test_guessing_codes_runs_into_the_limit(http: AsyncClient) -> None:
    # Well-formed but unknown codes are exactly what a guesser sends.
    statuses = [(await http.get(f"/Guess{n:02d}")).status_code for n in range(LIMIT + 2)]

    assert statuses == [404] * LIMIT + [429, 429]


async def test_junk_paths_are_rejected_without_being_counted(
    http: AsyncClient, logged_in: LoggedIn
) -> None:
    code = await make_code(http, logged_in)

    for _ in range(LIMIT + 5):
        assert (await http.get("/favicon.ico")).status_code == 404

    assert (await http.get(f"/{code}")).status_code == 302  # the limit was untouched
