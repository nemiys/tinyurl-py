"""Shared test setup.

The app refuses to start without a JWT secret (see settings.py), so tests
provide their own throwaway one. `setdefault` keeps a real value if somebody
exported one. This must run before the app's settings are first imported,
which is why it lives in conftest.py: pytest loads it before any test module.
"""

import logging
import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("JWT_SECRET", "test-only-secret-key-that-is-long-enough-for-hs256")


@pytest.fixture(autouse=True)
def restore_root_logger() -> Iterator[None]:
    """Starting the app sets up logging (see tinyurl_py.logs). Undo that after
    every test, so no test inherits the logging another one configured."""
    root = logging.getLogger()
    level, handlers = root.level, list(root.handlers)
    yield
    root.handlers[:] = handlers
    root.setLevel(level)
