"""Creating links."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pymongo.errors import DuplicateKeyError

from tinyurl_py.api.dependencies import CurrentUser, Database
from tinyurl_py.api.schemas import CreateLinkRequest, LinkPublic
from tinyurl_py.domain.codes import generate_code
from tinyurl_py.settings import settings

router = APIRouter(prefix="/links", tags=["links"])

# With ~3.5 trillion possible codes a collision is very rare, and five in a
# row is practically impossible unless the generator itself is broken.
MAX_CODE_ATTEMPTS = 5


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

        return LinkPublic(
            code=code,
            short_url=f"{settings.base_url}/{code}",
            url=link["url"],
            mobile_url=link["mobile_url"],
            expires_at=body.expires_at,
            created_at=created_at,
        )

    # 503 = "temporary problem, trying again will probably work".
    raise HTTPException(
        status_code=503,
        detail="Could not allocate a short code, please try again",
        headers={"Retry-After": "1"},
    )
