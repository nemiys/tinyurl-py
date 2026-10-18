"""POST /auth/register against a real Mongo (fixtures: see conftest.py)."""

from typing import Any

import pytest
from httpx import AsyncClient
from pymongo.asynchronous.database import AsyncDatabase

PASSWORD = "correct horse battery staple"


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
