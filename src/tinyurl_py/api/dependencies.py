"""Shared FastAPI dependencies.

A dependency is something an endpoint asks for as a parameter and FastAPI
supplies. Endpoints therefore never fetch their own database, which also lets
tests swap in a test database (`app.dependency_overrides`).
"""

from typing import Annotated, Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pymongo.asynchronous.database import AsyncDatabase
from redis.asyncio import Redis

from tinyurl_py.persistence.click_store import ClickStore, ClickStoreUnavailable, LazyClickStore
from tinyurl_py.persistence.mongo import DATABASE_NAME
from tinyurl_py.security.tokens import InvalidTokenError, decode_access_token


def get_db(request: Request) -> AsyncDatabase[dict[str, Any]]:
    # The client was created once at startup (see `lifespan` in main.py).
    db: AsyncDatabase[dict[str, Any]] = request.app.state.mongo[DATABASE_NAME]
    return db


# Endpoints write `db: Database` and get the object above.
Database = Annotated[AsyncDatabase[dict[str, Any]], Depends(get_db)]


def get_redis(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis


RedisClient = Annotated[Redis, Depends(get_redis)]


async def get_click_store(request: Request) -> ClickStore:
    lazy: LazyClickStore = request.app.state.clicks
    try:
        return await lazy.get()
    except ClickStoreUnavailable:
        # 503 = "temporary problem, try again". Only the endpoints that need
        # Cassandra ask for this dependency, so only they are affected.
        raise HTTPException(
            status_code=503,
            detail="Statistics are temporarily unavailable",
            headers={"Retry-After": "5"},
        ) from None


Clicks = Annotated[ClickStore, Depends(get_click_store)]


# Reads "Authorization: Bearer <token>". It also adds the Authorize button to
# Swagger. auto_error=False so that we answer with our own 401 below.
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Database,
) -> dict[str, Any]:
    """Turn the token in the request into the user's document, or answer 401.

    Endpoints that need a logged-in user just ask for `user: CurrentUser`; if
    anything below fails, their own code never runs.
    """
    unauthorized = HTTPException(
        status_code=401,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized

    try:
        user_id = ObjectId(decode_access_token(credentials.credentials))
    except (InvalidTokenError, InvalidId):
        raise unauthorized from None

    # The token is only a claim. Check the user still exists: the token of a
    # deleted account stays valid until it expires.
    user = await db.users.find_one({"_id": user_id})
    if user is None:
        raise unauthorized
    return user


CurrentUser = Annotated[dict[str, Any], Depends(get_current_user)]
