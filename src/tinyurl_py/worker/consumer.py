"""Reads click events from the Redis Stream and hands them to the store.

Guarantee: an event leaves the stream only after it has been saved
("at least once"). A crash can therefore make an event arrive twice, never
zero times; the store's idempotent write makes the repeat harmless.
"""

import asyncio
import logging
from contextlib import suppress
from typing import Any, Protocol

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from tinyurl_py.events.clicks import CLICKS_STREAM, ClickEvent

logger = logging.getLogger(__name__)

# Every worker joins this one group, so each message goes to exactly one of them.
GROUP = "click-workers"

# A message id with its fields; fields is None if the entry was deleted meanwhile.
type Message = tuple[str, dict[str, str] | None]


class ClickSaver(Protocol):
    async def save(self, event: ClickEvent) -> None: ...


def _messages(read_result: Any) -> list[Message]:
    """XREADGROUP answers [[stream, [message, ...]], ...]; we read one stream."""
    messages: list[Message] = []
    for _stream, stream_messages in read_result or []:
        messages.extend(stream_messages)
    return messages


class ClickConsumer:
    def __init__(
        self,
        redis: Redis,
        store: ClickSaver,
        name: str,
        *,
        claim_idle_ms: int = 60_000,
        block_ms: int = 2000,
        batch_size: int = 10,
        retry_delay_s: float = 1.0,
    ) -> None:
        self._redis = redis
        self._store = store
        self._name = name
        # A message pending longer than this is assumed to belong to a dead
        # worker. It must be far longer than saving one click takes, otherwise
        # we would steal work from a worker that is merely a bit slow.
        self._claim_idle_ms = claim_idle_ms
        self._block_ms = block_ms
        self._batch_size = batch_size
        self._retry_delay_s = retry_delay_s

    async def setup(self) -> None:
        """Create the group (and the stream) if they do not exist yet."""
        try:
            # id="0": the group starts from the very beginning of the stream, so
            # clicks published before the first worker ever ran are not skipped.
            await self._redis.xgroup_create(CLICKS_STREAM, GROUP, id="0", mkstream=True)
        except ResponseError as error:
            if "BUSYGROUP" not in str(error):  # BUSYGROUP = "already exists"
                raise

    async def run(self, stop: asyncio.Event) -> None:
        """Process events until `stop` is set. A failure never ends the loop:
        the unacknowledged message stays pending and is tried again."""
        await self.setup()
        while not stop.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("Could not process clicks; retrying shortly")
                with suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=self._retry_delay_s)

    async def run_once(self) -> int:
        """One pass over the three sources of work; returns how many messages
        were handled. Raises if saving fails (the message then stays pending)."""
        # 1. Messages given to us earlier but never acknowledged (we crashed, or
        #    saving failed). Reading from id "0" returns exactly those.
        handled = await self._handle_all(await self._read_own_pending())
        # 2. Messages another worker took and let sit too long: it is presumably dead.
        handled += await self._handle_all(await self._claim_stale())
        # 3. New messages. Wait for them only if nothing else needed doing.
        handled += await self._handle_all(await self._read_new(wait=handled == 0))
        return handled

    async def _read_own_pending(self) -> list[Message]:
        result = await self._redis.xreadgroup(
            GROUP, self._name, {CLICKS_STREAM: "0"}, count=self._batch_size
        )
        return _messages(result)

    async def _claim_stale(self) -> list[Message]:
        # XAUTOCLAIM transfers ownership of long-waiting messages to us and
        # returns them: [next cursor, messages, ids that no longer exist].
        result = await self._redis.xautoclaim(
            CLICKS_STREAM,
            GROUP,
            self._name,
            min_idle_time=self._claim_idle_ms,
            start_id="0-0",
            count=self._batch_size,
        )
        messages: list[Message] = result[1]
        return messages

    async def _read_new(self, *, wait: bool) -> list[Message]:
        # ">" means "messages nobody in the group has received yet".
        result = await self._redis.xreadgroup(
            GROUP,
            self._name,
            {CLICKS_STREAM: ">"},
            count=self._batch_size,
            block=self._block_ms if wait else None,
        )
        return _messages(result)

    async def _handle_all(self, messages: list[Message]) -> int:
        for message_id, fields in messages:
            await self._handle(message_id, fields)
        return len(messages)

    async def _handle(self, message_id: str, fields: dict[str, str] | None) -> None:
        event = self._parse(message_id, fields)
        if event is not None:
            # If this raises we never reach the acknowledgement below.
            await self._store.save(event)
        await self._finish(message_id)

    def _parse(self, message_id: str, fields: dict[str, str] | None) -> ClickEvent | None:
        if fields is None:
            return None
        try:
            return ClickEvent.model_validate_json(fields["data"])
        except (KeyError, ValidationError):
            # Retrying cannot fix a message that is broken, and it would sit at
            # the front of the queue forever. Only our own code writes to the
            # stream, so this means a bug: log loudly, keep the content.
            logger.error("Dropping unreadable message %s: %r", message_id, fields)
            return None

    async def _finish(self, message_id: str) -> None:
        # Acknowledge (it is no longer "pending") and delete (so the stream does
        # not grow forever), as one step so a crash cannot do only half.
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.xack(CLICKS_STREAM, GROUP, message_id)
            pipe.xdel(CLICKS_STREAM, message_id)
            await pipe.execute()
