"""POST /links refuses destinations that are not on the public internet.

Needs Mongo and Redis running. DNS answers are faked (see the autouse fixture in
conftest.py), so these tests never touch the network.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from pymongo.asynchronous.database import AsyncDatabase

from tests.integration.conftest import LoggedIn
from tinyurl_py.domain import urls
from tinyurl_py.settings import settings


async def create(http: AsyncClient, user: LoggedIn, **fields: str) -> Any:
    return await http.post("/links", json=fields, headers=user.headers)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/admin",
        "http://localhost:8001/me",
        "http://127.0.0.1:8080/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://[::1]/",
        "http://2130706433/",  # 127.0.0.1 written as a single number
        "http://0x7f.1/",
        "http://example.com@127.0.0.1/",  # the text before @ is just a user name
        "http://printer.local/",
        "http://intranet/",
    ],
)
async def test_internal_destinations_are_refused(
    http: AsyncClient, logged_in: LoggedIn, db: AsyncDatabase[dict[str, Any]], url: str
) -> None:
    response = await create(http, logged_in, url=url)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsafe_destination"
    assert await db.links.count_documents({}) == 0  # nothing was created


async def test_the_mobile_url_is_checked_too(http: AsyncClient, logged_in: LoggedIn) -> None:
    response = await create(
        http, logged_in, url="https://example.com/", mobile_url="http://192.168.1.1/m"
    )

    assert response.status_code == 422
    assert "mobile_url" in response.json()["error"]["message"]


async def test_a_name_that_resolves_to_an_internal_address_is_refused(
    http: AsyncClient, logged_in: LoggedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def resolve(host: str) -> list[str]:
        return ["127.0.0.1"] if host == "evil.example.net" else ["93.184.216.34"]

    monkeypatch.setattr(urls, "resolve_host", resolve)

    refused = await create(http, logged_in, url="https://evil.example.net/")
    accepted = await create(http, logged_in, url="https://good.example.org/")

    assert refused.status_code == 422
    assert accepted.status_code == 201


async def test_a_name_that_cannot_be_resolved_is_accepted(
    http: AsyncClient, logged_in: LoggedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def resolve(host: str) -> list[str]:
        raise OSError("no such host")

    monkeypatch.setattr(urls, "resolve_host", resolve)

    response = await create(http, logged_in, url="https://not-yet-live.example.org/")

    assert response.status_code == 201


async def test_a_link_to_this_service_is_refused(
    http: AsyncClient, logged_in: LoggedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "base_url", "https://sho.rt")

    response = await create(http, logged_in, url="https://sho.rt/aB3dE9x")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsafe_destination"
