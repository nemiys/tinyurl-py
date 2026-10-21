"""The demo data script. Needs Mongo, Redis and Cassandra from docker-compose.yml."""

from typing import Any

from httpx import AsyncClient
from pymongo.asynchronous.database import AsyncDatabase

from tests.integration.conftest import TODAY
from tests.integration.test_redirect import DESKTOP, PHONE
from tinyurl_py.seed import (
    DEMO_EMAIL,
    DEMO_LINKS,
    DEMO_PASSWORD,
    HISTORY_DAYS,
    seed_demo_data,
)


async def log_in(http: AsyncClient) -> dict[str, str]:
    response = await http.post("/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_the_demo_user_can_log_in_and_sees_the_demo_links(
    stats_web: AsyncClient,
    db: AsyncDatabase[dict[str, Any]],
    cassandra_session: Any,
    touched_links: list[str],
) -> None:
    result = await seed_demo_data(db, cassandra_session)
    touched_links.extend(result.link_ids.values())

    auth = await log_in(stats_web)
    listing = (await stats_web.get("/links", headers=auth)).json()

    assert {item["code"] for item in listing["items"]} == {link.code for link in DEMO_LINKS}


async def test_the_demo_links_behave_as_their_descriptions_say(
    stats_web: AsyncClient,
    db: AsyncDatabase[dict[str, Any]],
    cassandra_session: Any,
    touched_links: list[str],
) -> None:
    result = await seed_demo_data(db, cassandra_session)
    touched_links.extend(result.link_ids.values())
    plain, smart, expiring, expired = (link.code for link in DEMO_LINKS)

    assert (await stats_web.get(f"/{plain}")).status_code == 302
    on_phone = await stats_web.get(f"/{smart}", headers={"User-Agent": PHONE})
    on_desktop = await stats_web.get(f"/{smart}", headers={"User-Agent": DESKTOP})
    assert on_phone.headers["location"] != on_desktop.headers["location"]  # the smart link
    assert (await stats_web.get(f"/{expiring}")).status_code == 302
    assert (await stats_web.get(f"/{expired}")).status_code == 410  # expired days ago


async def test_the_statistics_match_what_was_written(
    stats_web: AsyncClient,
    db: AsyncDatabase[dict[str, Any]],
    cassandra_session: Any,
    touched_links: list[str],
) -> None:
    result = await seed_demo_data(db, cassandra_session)
    touched_links.extend(result.link_ids.values())
    auth = await log_in(stats_web)
    code = DEMO_LINKS[0].code

    stats = (await stats_web.get(f"/links/{code}/stats", headers=auth)).json()

    assert stats["total_clicks"] == result.clicks[code] > 0
    assert len(stats["days"]) == HISTORY_DAYS + 1  # the history plus today
    assert stats["days"][-1]["day"] == TODAY.isoformat()


async def test_running_it_again_resets_instead_of_duplicating(
    stats_web: AsyncClient,
    db: AsyncDatabase[dict[str, Any]],
    cassandra_session: Any,
    touched_links: list[str],
) -> None:
    first = await seed_demo_data(db, cassandra_session)
    second = await seed_demo_data(db, cassandra_session)
    touched_links.extend(first.link_ids.values())
    touched_links.extend(second.link_ids.values())
    auth = await log_in(stats_web)

    listing = (await stats_web.get("/links", headers=auth)).json()
    stats = (await stats_web.get(f"/links/{DEMO_LINKS[0].code}/stats", headers=auth)).json()

    assert listing["total"] == len(DEMO_LINKS)  # not twice as many
    assert await db.users.count_documents({"email": DEMO_EMAIL}) == 1
    assert stats["total_clicks"] == second.clicks[DEMO_LINKS[0].code]  # the old clicks are gone
    assert second.clicks == first.clicks  # and the numbers are the same every time
