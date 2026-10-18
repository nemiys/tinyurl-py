"""FastAPI application entrypoint."""

from fastapi import FastAPI

app = FastAPI(title="tinyurl-py")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
