"""Every error leaves the API in the same shape:

    {"error": {"code": "...", "message": "...", "details": [...]}}

Tested on a tiny app that only has the error handlers installed.
"""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, Field
from tinyurl_py.api.errors import install_error_handlers


class Body(BaseModel):
    secret: str = Field(min_length=8)


def make_app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/missing")
    async def missing() -> None:
        raise HTTPException(status_code=404, detail="Link not found")

    @app.get("/slow-down")
    async def slow_down() -> None:
        raise HTTPException(status_code=429, detail="Too many", headers={"Retry-After": "7"})

    @app.get("/typed")
    async def typed() -> None:
        raise HTTPException(
            status_code=422, detail={"code": "unsafe_destination", "message": "No internal URLs"}
        )

    @app.post("/body")
    async def post_body(body: Body) -> None:
        return None

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("the database password is hunter2")

    return app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    # raise_app_exceptions=False: behave like a real server, which answers 500
    # instead of letting the exception escape into the caller.
    transport = ASGITransport(app=make_app(), raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_an_http_error_has_a_code_and_a_message(client: AsyncClient) -> None:
    response = await client.get("/missing")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Link not found"}}


async def test_headers_of_the_error_are_kept(client: AsyncClient) -> None:
    response = await client.get("/slow-down")

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert response.headers["retry-after"] == "7"


async def test_an_error_can_bring_its_own_code(client: AsyncClient) -> None:
    response = await client.get("/typed")

    assert response.json() == {
        "error": {"code": "unsafe_destination", "message": "No internal URLs"}
    }


async def test_validation_errors_list_the_fields_and_never_echo_the_input(
    client: AsyncClient,
) -> None:
    response = await client.post("/body", json={"secret": "hunter"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"] == [
        {"field": "body.secret", "message": "String should have at least 8 characters"}
    ]
    assert "hunter" not in response.text  # the value somebody typed is not sent back


@pytest.mark.parametrize(
    ("method", "path", "status", "code"),
    [("GET", "/no-such-path", 404, "not_found"), ("DELETE", "/missing", 405, "method_not_allowed")],
)
async def test_errors_made_by_the_framework_look_the_same(
    client: AsyncClient, method: str, path: str, status: int, code: str
) -> None:
    response = await client.request(method, path)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code


async def test_an_unexpected_failure_is_a_plain_500_that_leaks_nothing(
    client: AsyncClient,
) -> None:
    response = await client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "Internal server error"}
    }
    assert "hunter2" not in response.text
