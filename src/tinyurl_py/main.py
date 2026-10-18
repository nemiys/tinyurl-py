"""FastAPI application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pymongo.errors import PyMongoError

from tinyurl_py.persistence.mongo import create_client


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Runs once when the app starts (before `yield`) and once when it stops
    # (after `yield`). The Mongo client is created here a single time and
    # parked on `app.state`, so every request can reach it.
    app.state.mongo = create_client()
    yield
    await app.state.mongo.close()


app = FastAPI(title="tinyurl-py", lifespan=lifespan)


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
