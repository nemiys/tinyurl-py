"""Integration test: needs the Mongo container from docker-compose.yml running."""

from tinyurl_py.persistence.mongo import create_client


async def test_mongo_answers_ping() -> None:
    client = create_client()
    try:
        # "ping" is Mongo's built-in "are you alive" command.
        result = await client.admin.command("ping")
    finally:
        await client.close()

    assert result["ok"] == 1
