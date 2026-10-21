"""Demo data: a user, four links and two weeks of clicks, so a fresh install is
not an empty page.

    uv run python -m tinyurl_py.seed
    docker compose exec api python -m tinyurl_py.seed

To remove the demo data and nothing else:  python -m tinyurl_py.seed --remove

Safe to run again: it first removes the demo user's previous links and clicks
(on every day, not only today), then creates them anew. The numbers are the
same every time (fixed random seed). The codes are fixed too, so documentation can point at them.
"""

import argparse
import asyncio
import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from tinyurl_py.events.clicks import ClickEvent
from tinyurl_py.persistence import cassandra
from tinyurl_py.persistence.click_store import ClickStore
from tinyurl_py.persistence.mongo import create_client, ensure_indexes
from tinyurl_py.security.passwords import hash_password
from tinyurl_py.settings import settings

DEMO_EMAIL = "demo@example.com"
# Public on purpose: this account exists only in demo data, never in a real setup.
DEMO_PASSWORD = "demo-password-123"
HISTORY_DAYS = 14

DELETE_DAY = "DELETE FROM clicks_by_link_day WHERE link_id = %s AND day = %s"


@dataclass(frozen=True)
class DemoLink:
    code: str
    url: str
    description: str
    mobile_url: str | None = None
    expires_in_days: int | None = None  # negative: it expired that many days ago
    max_clicks_per_day: int = 10


DEMO_LINKS = [
    DemoLink(
        "Demo001",
        "https://example.com/summer-sale",
        "a plain link with the busiest history",
        max_clicks_per_day=12,
    ),
    DemoLink(
        "Demo002",
        "https://example.com/app",
        "a smart link: phones are sent to the mobile address",
        mobile_url="https://m.example.com/app",
        max_clicks_per_day=8,
    ),
    DemoLink(
        "Demo003",
        "https://example.com/black-friday",
        "a link that expires in 30 days",
        expires_in_days=30,
        max_clicks_per_day=5,
    ),
    DemoLink(
        "Demo004",
        "https://example.com/old-campaign",
        "an expired link: answers 410 Gone, its statistics remain",
        expires_in_days=-3,
        max_clicks_per_day=3,
    ),
]


@dataclass(frozen=True)
class SeedResult:
    user_id: str
    link_ids: dict[str, str]  # code -> the id used in click events
    clicks: dict[str, int]  # code -> how many clicks were written


async def remove_demo_data(db: AsyncDatabase[dict[str, Any]], session: Any) -> None:
    """Delete the demo user, their links and every click of those links.

    Works from the links in Mongo, so it must run while they still exist: once
    they are gone, nothing says which Cassandra rows belonged to them."""
    user = await db.users.find_one({"email": DEMO_EMAIL})
    if user is None:
        return
    today = datetime.now(UTC).date()
    async for link in db.links.find({"owner_id": user["_id"]}):
        first_day = link["created_at"].astimezone(UTC).date()
        for offset in range((today - first_day).days + 1):
            day = first_day + timedelta(days=offset)
            await asyncio.to_thread(session.execute, DELETE_DAY, (str(link["_id"]), day))
    await db.links.delete_many({"owner_id": user["_id"]})
    await db.users.delete_one({"_id": user["_id"]})


def _click_events(
    link: DemoLink,
    link_id: str,
    created_at: datetime,
    expires_at: datetime | None,
    now: datetime,
    rng: random.Random,
) -> list[ClickEvent]:
    """Clicks for every day the link was alive, a different number each day."""
    mobile_share = 0.6 if link.mobile_url else 0.35
    events: list[ClickEvent] = []
    for offset in range((now.date() - created_at.date()).days + 1):
        day = created_at.date() + timedelta(days=offset)
        if expires_at is not None and day > expires_at.date():
            break  # nobody could click it any more
        for _ in range(rng.randint(0, link.max_clicks_per_day)):
            at = datetime.combine(day, time(rng.randint(0, 23), rng.randint(0, 59)), tzinfo=UTC)
            device = "mobile" if rng.random() < mobile_share else "desktop"
            events.append(
                ClickEvent.model_validate(
                    {
                        # Not uuid4(): the same ids every run keep the data identical.
                        "event_id": uuid.UUID(int=rng.getrandbits(128), version=4),
                        "link_id": link_id,
                        "clicked_at": min(at, now),  # nothing from the future
                        "device": device,
                    }
                )
            )
    return events


async def _save_all(store: ClickStore, events: list[ClickEvent]) -> None:
    """Write many clicks at once instead of one after another (a few hundred
    sequential writes took tens of seconds). Capped so Cassandra is not flooded."""
    gate = asyncio.Semaphore(16)

    async def save(event: ClickEvent) -> None:
        async with gate:
            await store.save(event)

    await asyncio.gather(*(save(event) for event in events))


async def seed_demo_data(db: AsyncDatabase[dict[str, Any]], session: Any) -> SeedResult:
    """(Re)create the demo user, links and clicks in the given databases."""
    await remove_demo_data(db, session)

    now = datetime.now(UTC)
    created_at = now - timedelta(days=HISTORY_DAYS)
    rng = random.Random(42)  # fixed: the demo looks the same on every machine

    user = await db.users.insert_one(
        {
            "email": DEMO_EMAIL,
            "password_hash": await asyncio.to_thread(hash_password, DEMO_PASSWORD),
            "created_at": created_at,
        }
    )

    store = await ClickStore.create(session)
    link_ids: dict[str, str] = {}
    clicks: dict[str, int] = {}
    for link in DEMO_LINKS:
        expires_at = (
            now + timedelta(days=link.expires_in_days) if link.expires_in_days is not None else None
        )
        inserted = await db.links.insert_one(
            {
                "code": link.code,
                "owner_id": user.inserted_id,
                "url": link.url,
                "mobile_url": link.mobile_url,
                "expires_at": expires_at,
                "created_at": created_at,
                "deleted_at": None,
            }
        )
        link_id = str(inserted.inserted_id)
        events = _click_events(link, link_id, created_at, expires_at, now, rng)
        await _save_all(store, events)
        link_ids[link.code] = link_id
        clicks[link.code] = len(events)

    return SeedResult(user_id=str(user.inserted_id), link_ids=link_ids, clicks=clicks)


async def main(remove: bool = False) -> None:
    mongo = create_client()
    db = mongo[settings.mongo_database]
    await ensure_indexes(db)
    session = await cassandra.connect()
    try:
        if remove:
            await remove_demo_data(db, session)
        else:
            result = await seed_demo_data(db, session)
    finally:
        await cassandra.close(session)
        await mongo.close()

    if remove:
        print("Demo data removed.")
        return

    print("Demo data is ready.\n")
    print(f"  Log in with   {DEMO_EMAIL}  /  {DEMO_PASSWORD}   (POST /auth/login, then Authorize)")
    print("  Short links:")
    for link in DEMO_LINKS:
        print(
            f"    {settings.base_url}/{link.code}  {link.description}"
            f" ({result.clicks[link.code]} clicks)"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create (or remove) the demo data.")
    parser.add_argument("--remove", action="store_true", help="remove the demo data and exit")
    asyncio.run(main(remove=parser.parse_args().remove))
