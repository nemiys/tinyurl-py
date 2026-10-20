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
from tinyurl_py.security.rate_limit import RateLimiter
from tinyurl_py.security.tokens import InvalidTokenError, decode_access_token
from tinyurl_py.settings import settings


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


def client_ip(request: Request) -> str:
    """Address of whoever connected to us.

    Deliberately NOT read from the X-Forwarded-For header: anyone can send that
    header, which would let a client pick a new "address" on every request and
    walk around the limit. Behind a real proxy, uvicorn can be told which
    proxies to trust (--forwarded-allow-ips) and then fills this in itself.
    """
    return request.client.host if request.client else "unknown"


async def enforce_rate_limit(
    redis: Redis, key: str, *, limit: int, window_seconds: int, detail: str
) -> None:
    """Answer 429 (with Retry-After) if `key` has used up its allowance."""
    result = await RateLimiter(redis).check(key, limit=limit, window_seconds=window_seconds)
    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail=detail,
            # Tells a well-behaved client exactly how long to wait.
            headers={"Retry-After": str(result.retry_after_seconds)},
        )


async def limit_link_creation(user: CurrentUser, redis: RedisClient) -> None:
    """Refuse once a user has created too many links recently.

    Runs after the login check (it needs to know who is asking), so a request
    without a valid token is a 401 and never counts. Per user and not per IP
    because people share IP addresses (an office, a home network).
    """
    await enforce_rate_limit(
        redis,
        f"create:user:{user['_id']}",
        limit=settings.create_link_limit,
        window_seconds=settings.create_link_window_seconds,
        detail="Too many links created, please slow down",
    )


async def limit_login(request: Request, redis: RedisClient) -> None:
    """Slow down password guessing: few login attempts per client IP.

    Runs before the password is checked. That check is deliberately slow
    (argon2), so refusing early also keeps a flood of attempts from loading
    the CPU. Successful logins count as well, so a guesser cannot mix in
    correct ones to confuse the count.
    """
    await enforce_rate_limit(
        redis,
        f"login:ip:{client_ip(request)}",
        limit=settings.login_limit,
        window_seconds=settings.login_window_seconds,
        detail="Too many login attempts, please wait",
    )
