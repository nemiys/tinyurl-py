"""DELETE /links/{code}: owner-only, and the cached copy must go too.

Needs the Mongo and Redis containers from docker-compose.yml running.
"""

from httpx import AsyncClient
from redis.asyncio import Redis, from_url

from tests.integration.conftest import LoggedIn
from tests.integration.test_get_link import register_other_user
from tinyurl_py.api.dependencies import get_redis
from tinyurl_py.main import app


async def create_link(web: AsyncClient, user: LoggedIn) -> str:
    response = await web.post(
        "/links", json={"url": "https://example.com/page"}, headers=user.headers
    )
    code: str = response.json()["code"]
    return code


async def test_owner_deletes_their_link(web: AsyncClient, logged_in: LoggedIn) -> None:
    code = await create_link(web, logged_in)

    response = await web.delete(f"/links/{code}", headers=logged_in.headers)

    assert response.status_code == 204
    assert (await web.get(f"/links/{code}", headers=logged_in.headers)).status_code == 404


async def test_deleted_link_stops_redirecting_even_if_it_was_cached(
    web: AsyncClient, logged_in: LoggedIn, redis_client: Redis
) -> None:
    code = await create_link(web, logged_in)
    await web.get(f"/{code}")  # a click fills the cache
    assert await redis_client.exists(f"link:{code}") == 1

    await web.delete(f"/links/{code}", headers=logged_in.headers)

    assert await redis_client.exists(f"link:{code}") == 0
    assert (await web.get(f"/{code}")).status_code == 404


async def test_deleting_twice_is_not_found(web: AsyncClient, logged_in: LoggedIn) -> None:
    code = await create_link(web, logged_in)
    await web.delete(f"/links/{code}", headers=logged_in.headers)

    response = await web.delete(f"/links/{code}", headers=logged_in.headers)

    assert response.status_code == 404


async def test_someone_elses_link_is_not_deleted(web: AsyncClient, logged_in: LoggedIn) -> None:
    code = await create_link(web, logged_in)
    other = await register_other_user(web)

    response = await web.delete(f"/links/{code}", headers=other.headers)

    assert response.status_code == 404
    assert (await web.get(f"/links/{code}", headers=logged_in.headers)).status_code == 200


async def test_login_is_required(web: AsyncClient, logged_in: LoggedIn) -> None:
    code = await create_link(web, logged_in)

    response = await web.delete(f"/links/{code}")

    assert response.status_code == 401


async def test_delete_succeeds_even_if_redis_is_down(web: AsyncClient, logged_in: LoggedIn) -> None:
    code = await create_link(web, logged_in)
    dead = from_url(
        "redis://localhost:1", decode_responses=True, socket_connect_timeout=0.5, socket_timeout=0.5
    )
    app.dependency_overrides[get_redis] = lambda: dead

    response = await web.delete(f"/links/{code}", headers=logged_in.headers)

    assert response.status_code == 204  # Mongo is the truth; the cache copy expires by itself
    await dead.aclose()
