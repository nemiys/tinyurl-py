"""POST /auth/login against a real Mongo (fixtures: see conftest.py)."""

from httpx import AsyncClient

from tinyurl_py.security.tokens import decode_access_token

PASSWORD = "correct horse battery staple"


async def register(http: AsyncClient, email: str = "dana@example.com") -> str:
    response = await http.post("/auth/register", json={"email": email, "password": PASSWORD})
    user_id: str = response.json()["id"]
    return user_id


async def test_login_returns_a_token_for_the_right_user(http: AsyncClient) -> None:
    user_id = await register(http)

    response = await http.post(
        "/auth/login", json={"email": "dana@example.com", "password": PASSWORD}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert decode_access_token(body["access_token"]) == user_id


async def test_wrong_password_is_unauthorized(http: AsyncClient) -> None:
    await register(http)

    response = await http.post(
        "/auth/login", json={"email": "dana@example.com", "password": "not the password"}
    )

    assert response.status_code == 401


async def test_unknown_email_gets_the_same_answer_as_a_wrong_password(http: AsyncClient) -> None:
    # Different answers would tell an attacker which emails are registered.
    await register(http)

    wrong_password = await http.post(
        "/auth/login", json={"email": "dana@example.com", "password": "not the password"}
    )
    unknown_email = await http.post(
        "/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
    )

    assert unknown_email.status_code == 401
    assert unknown_email.json() == wrong_password.json()


async def test_login_ignores_email_capitalisation(http: AsyncClient) -> None:
    await register(http)

    response = await http.post(
        "/auth/login", json={"email": "Dana@Example.com", "password": PASSWORD}
    )

    assert response.status_code == 200


async def test_login_with_a_missing_field_is_rejected(http: AsyncClient) -> None:
    response = await http.post("/auth/login", json={"email": "dana@example.com"})

    assert response.status_code == 422
