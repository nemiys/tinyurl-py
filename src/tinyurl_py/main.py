"""FastAPI application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError

from tinyurl_py.api.auth import router as auth_router
from tinyurl_py.api.errors import install_error_handlers
from tinyurl_py.api.links import router as links_router
from tinyurl_py.api.redirect import router as redirect_router
from tinyurl_py.api.users import router as users_router
from tinyurl_py.persistence.click_store import LazyClickStore
from tinyurl_py.persistence.mongo import create_client, ensure_indexes
from tinyurl_py.persistence.redis_client import create_redis
from tinyurl_py.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Runs once when the app starts (before `yield`) and once when it stops
    # (after `yield`). The Mongo client is created here a single time and
    # parked on `app.state`, so every request can reach it.
    app.state.mongo = create_client()
    # If Mongo is unreachable this raises and the app refuses to start: better
    # than running without the unique indexes that protect our data.
    await ensure_indexes(app.state.mongo[settings.mongo_database])
    # Redis is just a cache, so (unlike Mongo) the app starts without it.
    app.state.redis = create_redis()
    # Cassandra is only needed for statistics, so nothing connects yet: see
    # LazyClickStore.
    app.state.clicks = LazyClickStore()
    yield
    await app.state.clicks.close()
    await app.state.redis.aclose()
    await app.state.mongo.close()


app = FastAPI(title="tinyurl-py", lifespan=lifespan)
install_error_handlers(app)
app.include_router(auth_router)
app.include_router(links_router)
app.include_router(users_router)


@app.get("/health")
async def health() -> dict[str, str]:
    # Liveness: "the process is up". Deliberately does not touch any database,
    # so a database outage never makes a monitor restart a healthy app.
    return {"status": "ok"}


@app.get("/ready")
async def ready(request: Request) -> JSONResponse:
    # Readiness: "can the app do real work?" Right now that means Mongo.
    try:
        await request.app.state.mongo.admin.command("ping")
    except PyMongoError:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse(content={"status": "ready"})


# MUST stay at the very end of this file: /{code} matches any single-segment
# path, and routes are tried in the order they were registered. Anything added
# above this line (routers, /health, /ready, ...) is matched before it.
app.include_router(redirect_router)
