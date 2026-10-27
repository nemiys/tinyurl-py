"""Starting the API sets up logging. Needs Mongo running (the lifespan uses it)."""

import logging

from tinyurl_py.logs import HANDLER_NAME
from tinyurl_py.main import app


async def test_the_api_sets_up_logging_when_it_starts() -> None:
    async with app.router.lifespan_context(app):
        names = [handler.get_name() for handler in logging.getLogger().handlers]

    assert HANDLER_NAME in names
