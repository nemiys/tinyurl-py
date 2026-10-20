"""The API connects to Cassandra on first use, not at startup. Needs Cassandra."""

from typing import Any

import pytest

from tinyurl_py.persistence import click_store as click_store_module
from tinyurl_py.persistence.click_store import ClickStoreUnavailable, LazyClickStore


async def test_it_connects_on_first_use_and_then_reuses_the_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_connect = click_store_module.connect
    calls = 0

    async def counting_connect() -> Any:
        nonlocal calls
        calls += 1
        return await real_connect()

    monkeypatch.setattr(click_store_module, "connect", counting_connect)
    lazy = LazyClickStore()
    assert calls == 0  # nothing happens until somebody asks

    first = await lazy.get()
    second = await lazy.get()

    assert first is second
    assert calls == 1
    await lazy.close()


async def test_an_unreachable_cassandra_is_reported_and_retried_next_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_connect = click_store_module.connect

    async def broken_connect() -> Any:
        raise OSError("no route to cassandra")

    monkeypatch.setattr(click_store_module, "connect", broken_connect)
    lazy = LazyClickStore()

    with pytest.raises(ClickStoreUnavailable):
        await lazy.get()

    monkeypatch.setattr(click_store_module, "connect", real_connect)  # it came back
    assert await lazy.get() is not None
    await lazy.close()


async def test_closing_something_never_opened_is_harmless() -> None:
    await LazyClickStore().close()
