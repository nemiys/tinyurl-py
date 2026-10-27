"""Run the click worker:  uv run python -m tinyurl_py.worker"""

import asyncio
import logging
import signal

from tinyurl_py.logs import configure_logging
from tinyurl_py.persistence.cassandra import close, connect
from tinyurl_py.persistence.click_store import ClickStore
from tinyurl_py.persistence.redis_client import create_redis
from tinyurl_py.settings import settings
from tinyurl_py.worker.consumer import ClickConsumer

# Named explicitly: run as a program, __name__ is "__main__", which says nothing in a log line.
logger = logging.getLogger("tinyurl_py.worker")


async def main() -> None:
    # Longer than the 2s the consumer waits for messages, or every quiet moment
    # would count as a timeout.
    redis = create_redis(socket_timeout=10)
    session = await connect()
    try:
        store = await ClickStore.create(session)
        consumer = ClickConsumer(redis, store, settings.worker_name)

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                # Finish the message in hand, then leave (docker stop sends SIGTERM).
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:
                pass  # Windows: Ctrl-C raises KeyboardInterrupt instead.

        logger.info("Worker %s started", settings.worker_name)
        await consumer.run(stop)
    finally:
        await close(session)
        await redis.aclose()
        logger.info("Worker stopped")


if __name__ == "__main__":
    configure_logging()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
