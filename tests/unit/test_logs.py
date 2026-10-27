"""Our log lines carry their time, level and source."""

import io
import logging

from tinyurl_py.logs import HANDLER_NAME, configure_logging

# The root logger is restored after every test (tests/conftest.py).


def test_a_warning_shows_its_time_level_and_source() -> None:
    stream = io.StringIO()
    configure_logging(stream)

    logging.getLogger("tinyurl_py.cache.links").warning("Redis read failed")

    line = stream.getvalue().strip()
    assert line.endswith("WARNING tinyurl_py.cache.links Redis read failed")
    assert line[:4].isdigit()  # starts with the date, e.g. 2026-10-27


def test_info_messages_are_kept() -> None:
    stream = io.StringIO()
    configure_logging(stream)

    logging.getLogger("tinyurl_py.worker").info("Worker started")

    assert "INFO tinyurl_py.worker Worker started" in stream.getvalue()


def test_configuring_twice_prints_once() -> None:
    stream = io.StringIO()
    configure_logging(stream)
    configure_logging(stream)

    logging.getLogger("tinyurl_py").warning("once")

    assert stream.getvalue().count("once") == 1
    assert [h.get_name() for h in logging.getLogger().handlers].count(HANDLER_NAME) == 1
