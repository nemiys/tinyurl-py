"""The health endpoint is the app's smoke test: if it answers, the process is up."""

from httpx import ASGITransport, AsyncClient

from tinyurl_py.main import app


async def test_health_returns_ok() -> None:
    # ASGITransport calls the FastAPI app in-process: no real server or network.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
