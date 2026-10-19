"""POST /links against a real Mongo (fixtures: see conftest.py)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from bson import ObjectId
from httpx import AsyncClient
from pymongo.asynchronous.database import AsyncDatabase

from tests.integration.conftest import LoggedIn
from tinyurl_py.settings import settings

GENERATOR = "tinyurl_py.api.links.generate_code"


async def test_creating_a_link_requires_login(http: AsyncClient) -> None:
    response = await http.post("/links", json={"url": "https://example.com"})

    assert response.status_code == 401


async def test_created_link_is_returned_and_stored_with_its_owner(
    http: AsyncClient, db: AsyncDatabase[dict[str, Any]], logged_in: LoggedIn
) -> None:
    response = await http.post(
        "/links", json={"url": "https://example.com/page"}, headers=logged_in.headers
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"code", "short_url", "url", "mobile_url", "expires_at", "created_at"}
    assert len(body["code"]) == 7
    assert body["short_url"] == f"{settings.base_url}/{body['code']}"
    assert body["url"] == "https://example.com/page"
    assert body["mobile_url"] is None
    assert body["expires_at"] is None
    assert body["created_at"].endswith("Z")

    stored = await db.links.find_one({"code": body["code"]})
    assert stored is not None
    assert stored["owner_id"] == ObjectId(logged_in.user_id)
    assert stored["url"] == "https://example.com/page"


async def test_mobile_url_and_expiry_are_kept(http: AsyncClient, logged_in: LoggedIn) -> None:
    expires_at = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)

    response = await http.post(
        "/links",
        json={
            "url": "https://example.com",
            "mobile_url": "https://m.example.com",
            "expires_at": expires_at.isoformat(),
        },
        headers=logged_in.headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["mobile_url"] == "https://m.example.com/"
    assert datetime.fromisoformat(body["expires_at"]) == expires_at


@pytest.mark.parametrize("bad_url", ["javascript:alert(1)", "not a url", "ftp://example.com"])
async def test_unsafe_or_malformed_url_is_rejected(
    http: AsyncClient, logged_in: LoggedIn, bad_url: str
) -> None:
    response = await http.post("/links", json={"url": bad_url}, headers=logged_in.headers)

    assert response.status_code == 422


async def test_a_code_collision_is_retried_with_a_new_code(
    http: AsyncClient,
    db: AsyncDatabase[dict[str, Any]],
    logged_in: LoggedIn,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force the "one in a trillion" case: the first code drawn is already taken.
    codes = iter(["Taken00", "Fresh11"])
    monkeypatch.setattr(GENERATOR, lambda: next(codes))
    await db.links.insert_one({"code": "Taken00"})

    response = await http.post(
        "/links", json={"url": "https://example.com"}, headers=logged_in.headers
    )

    assert response.status_code == 201
    assert response.json()["code"] == "Fresh11"


async def test_giving_up_after_five_collisions_answers_503(
    http: AsyncClient,
    db: AsyncDatabase[dict[str, Any]],
    logged_in: LoggedIn,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def always_taken() -> str:
        nonlocal attempts
        attempts += 1
        return "Taken00"

    monkeypatch.setattr(GENERATOR, always_taken)
    await db.links.insert_one({"code": "Taken00"})

    response = await http.post(
        "/links", json={"url": "https://example.com"}, headers=logged_in.headers
    )

    assert response.status_code == 503
    assert attempts == 5
    assert await db.links.count_documents({}) == 1  # nothing extra was stored
