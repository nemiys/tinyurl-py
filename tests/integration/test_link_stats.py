"""GET /links/{code}/stats: click counts from Cassandra for the owner's link.

Needs Mongo, Redis and Cassandra from docker-compose.yml.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest
from bson import ObjectId
from httpx import AsyncClient
from pymongo.asynchronous.database import AsyncDatabase

from tests.integration.conftest import TODAY, LoggedIn, MakeLink
from tests.integration.test_get_link import register_other_user
from tinyurl_py.events.clicks import ClickEvent
from tinyurl_py.main import app
from tinyurl_py.persistence import cassandra as cassandra_module
from tinyurl_py.persistence.click_store import ClickStore, LazyClickStore


async def add_clicks(
    store: ClickStore, touched: list[str], link_id: str, day: date, count: int
) -> None:
    touched.append(link_id)
    at = datetime.combine(day, time(12), tzinfo=UTC)
    for _ in range(count):
        event = ClickEvent.model_validate(
            {"event_id": uuid.uuid4(), "link_id": link_id, "clicked_at": at, "device": "mobile"}
        )
        await store.save(event)


async def test_a_link_nobody_clicked_has_zero_clicks(
    stats_web: AsyncClient, logged_in: LoggedIn, make_link: MakeLink
) -> None:
    code, _ = await make_link()

    response = await stats_web.get(f"/links/{code}/stats", headers=logged_in.headers)

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == code
    assert body["total_clicks"] == 0
    assert body["deleted"] is False
    assert body["days"] == [{"day": TODAY.isoformat(), "clicks": 0}]  # created today


async def test_clicks_are_counted(
    stats_web: AsyncClient,
    logged_in: LoggedIn,
    click_store: ClickStore,
    touched_links: list[str],
    make_link: MakeLink,
) -> None:
    code, link_id = await make_link()
    await add_clicks(click_store, touched_links, link_id, TODAY, 3)

    body = (await stats_web.get(f"/links/{code}/stats", headers=logged_in.headers)).json()

    assert body["total_clicks"] == 3
    assert body["days"][-1] == {"day": TODAY.isoformat(), "clicks": 3}


async def test_total_covers_the_whole_life_but_days_only_the_requested_window(
    stats_web: AsyncClient,
    logged_in: LoggedIn,
    click_store: ClickStore,
    touched_links: list[str],
    db: AsyncDatabase[dict[str, Any]],
) -> None:
    created = datetime.now(UTC) - timedelta(days=40)
    inserted = await db.links.insert_one(
        {
            "code": "Old1234",
            "owner_id": ObjectId(logged_in.user_id),
            "url": "https://example.com/old",
            "mobile_url": None,
            "expires_at": None,
            "created_at": created,
            "deleted_at": None,
        }
    )
    link_id = str(inserted.inserted_id)
    await add_clicks(click_store, touched_links, link_id, TODAY - timedelta(days=35), 1)
    await add_clicks(click_store, touched_links, link_id, TODAY - timedelta(days=2), 2)
    await add_clicks(click_store, touched_links, link_id, TODAY, 1)

    default = (await stats_web.get("/links/Old1234/stats", headers=logged_in.headers)).json()
    wide = (await stats_web.get("/links/Old1234/stats?days=90", headers=logged_in.headers)).json()

    assert default["total_clicks"] == 4  # includes the click from 35 days ago
    assert len(default["days"]) == 30
    assert sum(entry["clicks"] for entry in default["days"]) == 3  # but that one is outside
    assert [entry["day"] for entry in default["days"]] == sorted(e["day"] for e in default["days"])
    assert len(wide["days"]) == 41  # never earlier than the day the link was created
    assert sum(entry["clicks"] for entry in wide["days"]) == 4


@pytest.mark.parametrize("query", ["days=0", "days=91", "days=-1", "days=abc"])
async def test_bad_window_sizes_are_rejected(
    stats_web: AsyncClient, logged_in: LoggedIn, query: str, make_link: MakeLink
) -> None:
    code, _ = await make_link()

    response = await stats_web.get(f"/links/{code}/stats?{query}", headers=logged_in.headers)

    assert response.status_code == 422


async def test_someone_elses_link_and_unknown_codes_are_not_found(
    stats_web: AsyncClient, logged_in: LoggedIn, make_link: MakeLink
) -> None:
    code, _ = await make_link()
    other = await register_other_user(stats_web)

    theirs = await stats_web.get(f"/links/{code}/stats", headers=other.headers)
    missing = await stats_web.get("/links/Missing/stats", headers=other.headers)

    assert theirs.status_code == missing.status_code == 404
    assert theirs.json() == missing.json()


async def test_login_is_required(
    stats_web: AsyncClient, logged_in: LoggedIn, make_link: MakeLink
) -> None:
    code, _ = await make_link()

    response = await stats_web.get(f"/links/{code}/stats")

    assert response.status_code == 401


async def test_statistics_of_a_deleted_link_stay_reachable(
    stats_web: AsyncClient,
    logged_in: LoggedIn,
    click_store: ClickStore,
    touched_links: list[str],
    make_link: MakeLink,
) -> None:
    code, link_id = await make_link()
    await add_clicks(click_store, touched_links, link_id, TODAY, 2)
    await stats_web.delete(f"/links/{code}", headers=logged_in.headers)

    response = await stats_web.get(f"/links/{code}/stats", headers=logged_in.headers)

    assert response.status_code == 200
    assert response.json()["total_clicks"] == 2
    assert response.json()["deleted"] is True


async def test_stats_answer_503_while_cassandra_is_unreachable_and_nothing_else_breaks(
    web: AsyncClient, logged_in: LoggedIn, monkeypatch: pytest.MonkeyPatch, make_link: MakeLink
) -> None:
    async def broken_connect() -> Any:
        raise OSError("no route to cassandra")

    monkeypatch.setattr(cassandra_module, "connect", broken_connect)
    monkeypatch.setattr(app.state, "clicks", LazyClickStore(), raising=False)
    code, _ = await make_link()

    stats = await web.get(f"/links/{code}/stats", headers=logged_in.headers)
    redirect = await web.get(f"/{code}")

    assert stats.status_code == 503
    assert stats.headers["retry-after"]
    assert redirect.status_code == 302  # the rest of the service does not care
