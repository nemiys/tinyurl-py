"""GET /links: my links, newest first, in pages. Needs Mongo running."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from bson import ObjectId
from httpx import AsyncClient
from pymongo.asynchronous.database import AsyncDatabase

from tests.integration.conftest import LoggedIn
from tests.integration.test_get_link import register_other_user

START = datetime(2026, 1, 1, tzinfo=UTC)


async def insert_links(
    db: AsyncDatabase[dict[str, Any]], owner_id: str, count: int, *, same_time: bool = False
) -> list[str]:
    """Insert `count` links straight into Mongo (faster than going through the API).
    Codes are L0, L1, ... and link N is N minutes newer than link 0."""
    documents = [
        {
            "code": f"L{n}",
            "owner_id": ObjectId(owner_id),
            "url": f"https://example.com/{n}",
            "mobile_url": None,
            "expires_at": None,
            "created_at": START if same_time else START + timedelta(minutes=n),
        }
        for n in range(count)
    ]
    await db.links.insert_many(documents)
    return [f"L{n}" for n in range(count)]


async def test_no_links_gives_an_empty_page(http: AsyncClient, logged_in: LoggedIn) -> None:
    response = await http.get("/links", headers=logged_in.headers)

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


async def test_newest_link_comes_first(
    http: AsyncClient, logged_in: LoggedIn, db: AsyncDatabase[dict[str, Any]]
) -> None:
    await insert_links(db, logged_in.user_id, 3)

    body = (await http.get("/links", headers=logged_in.headers)).json()

    assert [item["code"] for item in body["items"]] == ["L2", "L1", "L0"]
    assert body["total"] == 3


async def test_only_my_links_are_listed(
    http: AsyncClient, logged_in: LoggedIn, db: AsyncDatabase[dict[str, Any]]
) -> None:
    other = await register_other_user(http)
    await db.links.insert_one(
        {
            "code": "Mine123",
            "owner_id": ObjectId(logged_in.user_id),
            "url": "https://example.com/a",
            "mobile_url": None,
            "expires_at": None,
            "created_at": START,
        }
    )
    await db.links.insert_one(
        {
            "code": "Theirs1",
            "owner_id": ObjectId(other.user_id),
            "url": "https://example.com/b",
            "mobile_url": None,
            "expires_at": None,
            "created_at": START,
        }
    )

    body = (await http.get("/links", headers=logged_in.headers)).json()

    assert [item["code"] for item in body["items"]] == ["Mine123"]
    assert body["total"] == 1


async def test_limit_and_offset_pick_a_page(
    http: AsyncClient, logged_in: LoggedIn, db: AsyncDatabase[dict[str, Any]]
) -> None:
    await insert_links(db, logged_in.user_id, 5)  # newest first: L4 L3 L2 L1 L0

    body = (await http.get("/links?limit=2&offset=1", headers=logged_in.headers)).json()

    assert [item["code"] for item in body["items"]] == ["L3", "L2"]
    assert body["total"] == 5  # total counts all my links, not just this page
    assert (body["limit"], body["offset"]) == (2, 1)


async def test_default_page_size_is_20(
    http: AsyncClient, logged_in: LoggedIn, db: AsyncDatabase[dict[str, Any]]
) -> None:
    await insert_links(db, logged_in.user_id, 25)

    body = (await http.get("/links", headers=logged_in.headers)).json()

    assert len(body["items"]) == 20
    assert body["total"] == 25


async def test_offset_past_the_end_gives_an_empty_page(
    http: AsyncClient, logged_in: LoggedIn, db: AsyncDatabase[dict[str, Any]]
) -> None:
    await insert_links(db, logged_in.user_id, 3)

    body = (await http.get("/links?offset=10", headers=logged_in.headers)).json()

    assert body["items"] == []
    assert body["total"] == 3


async def test_links_created_at_the_same_moment_never_repeat_or_vanish_across_pages(
    http: AsyncClient, logged_in: LoggedIn, db: AsyncDatabase[dict[str, Any]]
) -> None:
    expected = await insert_links(db, logged_in.user_id, 5, same_time=True)

    seen: list[str] = []
    for offset in (0, 2, 4):
        page = await http.get(f"/links?limit=2&offset={offset}", headers=logged_in.headers)
        seen += [item["code"] for item in page.json()["items"]]

    assert sorted(seen) == sorted(expected)  # all five, each exactly once


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "limit=-5", "offset=-1", "limit=abc"])
async def test_bad_paging_values_are_rejected(
    http: AsyncClient, logged_in: LoggedIn, query: str
) -> None:
    response = await http.get(f"/links?{query}", headers=logged_in.headers)

    assert response.status_code == 422


async def test_maximum_page_size_is_accepted(http: AsyncClient, logged_in: LoggedIn) -> None:
    response = await http.get("/links?limit=100", headers=logged_in.headers)

    assert response.status_code == 200


async def test_login_is_required(http: AsyncClient) -> None:
    response = await http.get("/links")

    assert response.status_code == 401
