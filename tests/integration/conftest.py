"""Fixtures shared by the API integration tests.

They need the Mongo container from docker-compose.yml running. Everything
happens in a separate `tinyurl_test` database that is wiped around each test.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pymongo.asynchronous.database import AsyncDatabase
from redis.asyncio import Redis, from_url

from tinyurl_py.api.dependencies import get_click_store, get_db, get_redis
from tinyurl_py.domain import urls
from tinyurl_py.main import app
from tinyurl_py.persistence.cassandra import close, connect
from tinyurl_py.persistence.click_store import ClickStore
from tinyurl_py.persistence.mongo import create_client, ensure_indexes
from tinyurl_py.settings import settings

TEST_DATABASE = "tinyurl_test"


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every name resolves to a public address, so tests never touch the network
    (and do not depend on whether example.com happens to be reachable)."""

    async def resolve(host: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(urls, "resolve_host", resolve)


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
async def http(
    db: AsyncDatabase[dict[str, Any]], redis_client: Redis
) -> AsyncIterator[AsyncClient]:
    # Swap the real databases for the test ones, only for the duration of a test.
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_redis] = lambda: redis_client
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
async def web(http: AsyncClient) -> AsyncClient:
    """Same client as `http`; older tests use this name."""
    return http


# Cassandra and click statistics, shared by several test files.

DELETE_DAY = "DELETE FROM clicks_by_link_day WHERE link_id = %s AND day = %s"
TODAY = datetime.now(UTC).date()


@pytest.fixture
def touched_links() -> list[str]:
    """Links that got clicks in Cassandra, so the fixture below can clean up."""
    return []


@pytest.fixture(scope="session")
def cassandra_session() -> Iterator[Any]:
    """One Cassandra connection for the whole test run: connecting takes over a
    second, and doing it for every test doubled the time of the suite. The driver
    runs on its own threads, so the session works from any test's event loop."""
    session = asyncio.run(connect())
    yield session
    asyncio.run(close(session))


@pytest.fixture
def session(cassandra_session: Any) -> Any:
    """Same connection, under the name the Cassandra tests use."""
    return cassandra_session


@pytest.fixture
async def click_store(
    cassandra_session: Any, touched_links: list[str]
) -> AsyncIterator[ClickStore]:
    store = await ClickStore.create(cassandra_session)
    yield store
    await asyncio.gather(
        *(
            asyncio.to_thread(
                cassandra_session.execute, DELETE_DAY, (link_id, TODAY - timedelta(days=back))
            )
            for link_id in touched_links
            for back in range(60)
        )
    )


@pytest.fixture
async def stats_web(web: AsyncClient, click_store: ClickStore) -> AsyncClient:
    app.dependency_overrides[get_click_store] = lambda: click_store
    return web


type MakeLink = Callable[[], Awaitable[tuple[str, str]]]


@pytest.fixture
def make_link(web: AsyncClient, logged_in: LoggedIn, db: AsyncDatabase[dict[str, Any]]) -> MakeLink:
    """Creates a link through the API. Returns (code, link_id), where link_id is
    the id the click events (and so the Cassandra rows) use."""

    async def make() -> tuple[str, str]:
        body = {"url": "https://example.com/p"}
        response = await web.post("/links", json=body, headers=logged_in.headers)
        code: str = response.json()["code"]
        document = await db.links.find_one({"code": code})
        assert document is not None
        return code, str(document["_id"])

    return make
