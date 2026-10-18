"""The unique indexes are what actually enforces "one email / one code only".

Needs the Mongo container from docker-compose.yml running. Uses a separate
`tinyurl_test` database that is wiped before and after each test.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from tinyurl_py.persistence.mongo import create_client, ensure_indexes

TEST_DATABASE = "tinyurl_test"


@pytest.fixture
async def db() -> AsyncIterator[AsyncDatabase[dict[str, Any]]]:
    client = create_client()
    await client.drop_database(TEST_DATABASE)
    yield client[TEST_DATABASE]
    await client.drop_database(TEST_DATABASE)
    await client.close()


async def test_second_user_with_same_email_is_rejected(
    db: AsyncDatabase[dict[str, Any]],
) -> None:
    await ensure_indexes(db)
    await db.users.insert_one({"email": "dana@example.com"})

    with pytest.raises(DuplicateKeyError):
        await db.users.insert_one({"email": "dana@example.com"})


async def test_second_link_with_same_code_is_rejected(
    db: AsyncDatabase[dict[str, Any]],
) -> None:
    await ensure_indexes(db)
    await db.links.insert_one({"code": "aB3dE9x"})

    with pytest.raises(DuplicateKeyError):
        await db.links.insert_one({"code": "aB3dE9x"})


async def test_ensure_indexes_can_run_twice(db: AsyncDatabase[dict[str, Any]]) -> None:
    # It runs on every app start, so a second run must be harmless.
    await ensure_indexes(db)
    await ensure_indexes(db)
