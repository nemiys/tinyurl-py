"""Creating, listing, reading and deleting links."""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pymongo import DESCENDING
from pymongo.errors import DuplicateKeyError

from tinyurl_py.api.dependencies import CurrentUser, Database, RedisClient
from tinyurl_py.api.schemas import CreateLinkRequest, LinkPage, LinkPublic
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
) -> LinkPage:
    mine = {"owner_id": user["_id"]}
    total = await db.links.count_documents(mine)
    # Newest first; `_id` breaks ties so the order never changes between calls.
    cursor = (
        db.links.find(mine)
        .sort([("created_at", DESCENDING), ("_id", DESCENDING)])
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
    link = await db.links.find_one({"code": code, "owner_id": user["_id"]})
    if link is None:
        raise HTTPException(status_code=404, detail="Link not found")
    return to_public(link)


@router.delete(
    "/{code}",
    status_code=204,
    responses={
        401: {"description": "Missing, invalid or expired token"},
        404: {"description": "No such link, or it belongs to someone else"},
    },
)
async def delete_link(code: str, user: CurrentUser, db: Database, redis: RedisClient) -> None:
    # Mongo first: it is the source of truth. Had we cleared the cache first, a
    # click arriving in between would copy the link back into it.
    result = await db.links.delete_one({"code": code, "owner_id": user["_id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Link not found")

    # Without this the deleted link would keep redirecting until its cached
    # copy expires (up to an hour).
    await delete_cached_link(redis, code)
