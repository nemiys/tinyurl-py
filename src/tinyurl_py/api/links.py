"""Creating, listing, reading, deleting and measuring links."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError

from tinyurl_py.api.dependencies import Clicks, CurrentUser, Database, RedisClient
from tinyurl_py.api.schemas import CreateLinkRequest, DayClicks, LinkPage, LinkPublic, LinkStats
from tinyurl_py.cache.links import delete_cached_link
from tinyurl_py.domain.codes import generate_code
from tinyurl_py.settings import settings

router = APIRouter(prefix="/links", tags=["links"])

# With ~3.5 trillion possible codes a collision is very rare, and five in a
# row is practically impossible unless the generator itself is broken.
MAX_CODE_ATTEMPTS = 5

DEFAULT_PAGE_SIZE = 20
# Without an upper bound, `?limit=1000000` would make one request drag the
# whole collection through the server.
MAX_PAGE_SIZE = 100

DEFAULT_STATS_DAYS = 30
MAX_STATS_DAYS = 90


def to_public(link: dict[str, Any]) -> LinkPublic:
    """A link as stored in Mongo -> what we show the outside world."""
    return LinkPublic(
        code=link["code"],
        short_url=f"{settings.base_url}/{link['code']}",
        url=link["url"],
        mobile_url=link["mobile_url"],
        expires_at=link["expires_at"],
        created_at=link["created_at"],
    )


@router.post(
    "",
    status_code=201,
    response_model=LinkPublic,
    responses={
        401: {"description": "Missing, invalid or expired token"},
        503: {"description": "No free short code was found; try again"},
    },
)
async def create_link(body: CreateLinkRequest, user: CurrentUser, db: Database) -> LinkPublic:
    created_at = datetime.now(UTC)
    link = {
        "owner_id": user["_id"],
        "url": str(body.url),
        "mobile_url": str(body.mobile_url) if body.mobile_url is not None else None,
        "expires_at": body.expires_at,
        "created_at": created_at,
        # None = alive. Deleting sets the time instead of removing the row.
        "deleted_at": None,
    }

    for _ in range(MAX_CODE_ATTEMPTS):
        code = generate_code()
        try:
            # No "is this code free?" check first: someone else could take it
            # between the check and the write. We just write, and the unique
            # index on `code` refuses duplicates. (insert_one adds an `_id` to
            # the dict it gets, hence a fresh dict on every attempt.)
            await db.links.insert_one({"code": code, **link})
        except DuplicateKeyError:
            continue

        return to_public({"code": code, **link})

    # 503 = "temporary problem, trying again will probably work".
    raise HTTPException(
        status_code=503,
        detail="Could not allocate a short code, please try again",
        headers={"Retry-After": "1"},
    )


@router.get(
    "",
    response_model=LinkPage,
    responses={401: {"description": "Missing, invalid or expired token"}},
)
async def list_links(
    user: CurrentUser,
    db: Database,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: Literal["all", "active", "expired"] = "all",
    order: Literal["asc", "desc"] = "desc",
) -> LinkPage:
    # `Literal` is a closed list: any other value is a 422, so nobody can
    # smuggle an arbitrary word into the query.
    query: dict[str, Any] = {"owner_id": user["_id"], "deleted_at": None}
    now = datetime.now(UTC)
    if status == "active":
        # No expiry date at all also means "still active".
        query["$or"] = [{"expires_at": None}, {"expires_at": {"$gt": now}}]
    elif status == "expired":
        query["expires_at"] = {"$lte": now}

    total = await db.links.count_documents(query)
    direction = ASCENDING if order == "asc" else DESCENDING
    # `_id` breaks ties so the order never changes between calls.
    cursor = (
        db.links.find(query)
        .sort([("created_at", direction), ("_id", direction)])
        .skip(offset)
        .limit(limit)
    )
    documents = await cursor.to_list()
    return LinkPage(
        items=[to_public(document) for document in documents],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{code}",
    response_model=LinkPublic,
    responses={
        401: {"description": "Missing, invalid or expired token"},
        404: {"description": "No such link, or it belongs to someone else"},
    },
)
async def get_link(code: str, user: CurrentUser, db: Database) -> LinkPublic:
    # Filtering by owner in the query itself means a stranger's link is simply
    # "not found": the answer is identical to an unknown code, so nobody can
    # use this endpoint to discover which codes exist.
    link = await db.links.find_one({"code": code, "owner_id": user["_id"], "deleted_at": None})
    if link is None:
        raise HTTPException(status_code=404, detail="Link not found")
    return to_public(link)


@router.get(
    "/{code}/stats",
    response_model=LinkStats,
    responses={
        401: {"description": "Missing, invalid or expired token"},
        404: {"description": "No such link, or it belongs to someone else"},
        503: {"description": "Statistics are temporarily unavailable"},
    },
)
async def get_link_stats(
    code: str,
    user: CurrentUser,
    db: Database,
    clicks: Clicks,
    days: Annotated[int, Query(ge=1, le=MAX_STATS_DAYS)] = DEFAULT_STATS_DAYS,
) -> LinkStats:
    # No `deleted_at` filter on purpose: a deleted link keeps its statistics.
    link = await db.links.find_one({"code": code, "owner_id": user["_id"]})
    if link is None:
        raise HTTPException(status_code=404, detail="Link not found")

    # Count every day from the day the link was created until today, because the
    # total covers the link's whole life. Days are UTC, like the rows.
    today = datetime.now(UTC).date()
    first_day = link["created_at"].astimezone(UTC).date()
    all_days = [first_day + timedelta(days=n) for n in range((today - first_day).days + 1)]
    counts = await clicks.count_per_day(str(link["_id"]), all_days)

    # Only the last `days` days are listed; the total still includes the rest.
    window = list(zip(all_days, counts, strict=True))[-days:]
    return LinkStats(
        code=code,
        total_clicks=sum(counts),
        days=[DayClicks(day=day, clicks=count) for day, count in window],
        deleted=link.get("deleted_at") is not None,
    )


@router.delete(
    "/{code}",
    status_code=204,
    responses={
        401: {"description": "Missing, invalid or expired token"},
        404: {"description": "No such link, or it belongs to someone else"},
    },
)
async def delete_link(code: str, user: CurrentUser, db: Database, redis: RedisClient) -> None:
    # Soft delete: the row stays, marked with the time. That keeps the link's
    # statistics reachable and keeps its code taken (the unique index still
    # sees it), so the code can never be handed to a new link.
    # `"deleted_at": None` also skips links that were already deleted.
    #
    # Mongo first: it is the source of truth. Had we cleared the cache first, a
    # click arriving in between would copy the link back into it.
    result = await db.links.update_one(
        {"code": code, "owner_id": user["_id"], "deleted_at": None},
        {"$set": {"deleted_at": datetime.now(UTC)}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Link not found")

    # Without this the deleted link would keep redirecting until its cached
    # copy expires (up to an hour).
    await delete_cached_link(redis, code)
