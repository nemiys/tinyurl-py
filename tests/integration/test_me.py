"""GET /me: the first protected endpoint (fixtures: see conftest.py)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from httpx import AsyncClient
from pymongo.asynchronous.database import AsyncDatabase

from tinyurl_py.security.tokens import create_access_token

PASSWORD = "correct horse battery staple"


async def register_and_login(http: AsyncClient) -> tuple[str, str]:
    """Return (user_id, access_token) of a freshly registered user."""
    registered = await http.post(
        "/auth/register", json={"email": "dana@example.com", "password": PASSWORD}
    )
    logged_in = await http.post(
        "/auth/login", json={"email": "dana@example.com", "password": PASSWORD}
    )
    return registered.json()["id"], logged_in.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_me_returns_the_logged_in_user_without_secrets(http: AsyncClient) -> None:
    user_id, token = await register_and_login(http)

    response = await http.get("/me", headers=bearer(token))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"id", "email", "created_at"}
    assert body["id"] == user_id
    assert body["email"] == "dana@example.com"


async def test_me_without_a_token_is_unauthorized(http: AsyncClient) -> None:
    response = await http.get("/me")

    assert response.status_code == 401


async def test_me_with_a_garbage_token_is_unauthorized(http: AsyncClient) -> None:
    response = await http.get("/me", headers=bearer("definitely-not-a-token"))

    assert response.status_code == 401


async def test_me_with_an_expired_token_is_unauthorized(http: AsyncClient) -> None:
    user_id, _ = await register_and_login(http)
    expired = create_access_token(user_id, expires_in=timedelta(seconds=-1))

    response = await http.get("/me", headers=bearer(expired))

    assert response.status_code == 401


async def test_me_with_a_forged_token_is_unauthorized(http: AsyncClient) -> None:
    user_id, _ = await register_and_login(http)
    forged = jwt.encode(
        {"sub": user_id, "exp": datetime.now(UTC) + timedelta(minutes=5)},
        "a-completely-different-secret-key-of-enough-length",
        algorithm="HS256",
    )

    response = await http.get("/me", headers=bearer(forged))

    assert response.status_code == 401


async def test_valid_token_of_a_deleted_user_is_unauthorized(
    http: AsyncClient, db: AsyncDatabase[dict[str, Any]]
) -> None:
    # The token itself is still perfectly valid; only the user is gone.
    _, token = await register_and_login(http)
    await db.users.delete_many({})

    response = await http.get("/me", headers=bearer(token))

    assert response.status_code == 401


async def test_me_with_another_authentication_scheme_is_unauthorized(http: AsyncClient) -> None:
    response = await http.get("/me", headers={"Authorization": "Basic ZGFuYTpwYXNz"})

    assert response.status_code == 401
