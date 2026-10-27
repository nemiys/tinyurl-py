"""One log format for the API and the worker.

Without this, Python prints our warnings bare (no time, no level, no source)
and drops INFO messages altogether. Uvicorn's own lines are unaffected: its
loggers have their own handlers and do not pass their records up to the root.
"""

import logging
from typing import TextIO

# Time, level, which module spoke, what it said:
#   2026-10-27 10:15:02,118 WARNING tinyurl_py.cache.links Redis read failed ...
FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

# Marks our handler, so a second call can see it is already in place.
HANDLER_NAME = "tinyurl_py"


def configure_logging(stream: TextIO | None = None) -> None:
    """Send log records (INFO and up) to `stream`, by default stderr.

    Safe to call more than once: the handler is added only the first time,
    so no line is ever printed twice.
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if any(handler.get_name() == HANDLER_NAME for handler in root.handlers):
        return
    handler = logging.StreamHandler(stream)
    handler.set_name(HANDLER_NAME)
    handler.setFormatter(logging.Formatter(FORMAT))
    root.addHandler(handler)
