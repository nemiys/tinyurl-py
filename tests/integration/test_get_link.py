"""GET /links/{code}: one link, visible only to its owner. Needs Mongo running."""

from httpx import AsyncClient

from tests.integration.conftest import LoggedIn


async def create_link(http: AsyncClient, user: LoggedIn) -> str:
    response = await http.post(
        "/links", json={"url": "https://example.com/page"}, headers=user.headers
    )
    code: str = response.json()["code"]
    return code


async def register_other_user(http: AsyncClient) -> LoggedIn:
    credentials = {"email": "sara@example.com", "password": "another long passphrase"}
    registered = await http.post("/auth/register", json=credentials)
    login = await http.post("/auth/login", json=credentials)
    token = login.json()["access_token"]
    return LoggedIn(user_id=registered.json()["id"], headers={"Authorization": f"Bearer {token}"})


async def test_owner_sees_their_link(http: AsyncClient, logged_in: LoggedIn) -> None:
    code = await create_link(http, logged_in)

    response = await http.get(f"/links/{code}", headers=logged_in.headers)

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == code
    assert body["url"] == "https://example.com/page"


async def test_unknown_code_is_not_found(http: AsyncClient, logged_in: LoggedIn) -> None:
    response = await http.get("/links/Missing", headers=logged_in.headers)

    assert response.status_code == 404


async def test_someone_elses_link_looks_like_it_does_not_exist(
    http: AsyncClient, logged_in: LoggedIn
) -> None:
    code = await create_link(http, logged_in)
    other = await register_other_user(http)

    response = await http.get(f"/links/{code}", headers=other.headers)

    # Same answer as for an unknown code, so a stranger learns nothing.
    assert response.status_code == 404
    assert response.json() == (await http.get("/links/Missing", headers=other.headers)).json()


async def test_login_is_required(http: AsyncClient, logged_in: LoggedIn) -> None:
    code = await create_link(http, logged_in)

    response = await http.get(f"/links/{code}")

    assert response.status_code == 401
