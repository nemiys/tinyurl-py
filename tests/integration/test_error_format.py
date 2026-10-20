"""The error format on the real app. Needs Mongo and Redis running."""

import pytest
from httpx import AsyncClient

from tests.integration.conftest import LoggedIn
from tinyurl_py.settings import settings


async def test_unauthorized_keeps_its_header_and_gets_the_standard_body(
    http: AsyncClient,
) -> None:
    response = await http.get("/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.headers["www-authenticate"] == "Bearer"


async def test_not_found_has_the_standard_body(http: AsyncClient, logged_in: LoggedIn) -> None:
    response = await http.get("/links/Missing", headers=logged_in.headers)

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Link not found"}}


async def test_invalid_input_lists_the_fields_without_echoing_the_password(
    http: AsyncClient,
) -> None:
    response = await http.post("/auth/register", json={"email": "not-an-email", "password": "pw"})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert {detail["field"] for detail in error["details"]} == {"body.email", "body.password"}
    assert '"pw"' not in response.text


async def test_rate_limit_answers_in_the_same_shape(
    http: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "login_limit", 1)
    body = {"email": "dana@example.com", "password": "whatever it is"}
    await http.post("/auth/login", json=body)

    response = await http.post("/auth/login", json=body)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert int(response.headers["retry-after"]) >= 1
