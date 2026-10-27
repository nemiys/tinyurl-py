"""Click events: what we record on every redirect, and how it reaches the queue.

The redirect only drops a small message into a Redis Stream and moves on. A
separate worker turns those messages into rows in Cassandra, so a slow
database never delays anybody's redirect.
"""

import logging
from datetime import UTC, datetime
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, Field
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

# The name of the Stream (Redis's append-only message queue).
CLICKS_STREAM = "clicks"


class ClickEvent(BaseModel):
    # Created once, here, at the moment of the click. If the same event is ever
    # delivered twice, both copies carry the same id and the same time, so the
    # worker writes the same Cassandra key and the second write overwrites the
    # first instead of counting a second click.
    event_id: UUID
    link_id: str  # the link's Mongo _id (its permanent identity), not its public code
    clicked_at: AwareDatetime
    device: Literal["mobile", "desktop"] = Field(examples=["mobile"])

    @classmethod
    def new(cls, link_id: str, device: Literal["mobile", "desktop"]) -> Self:
        return cls(event_id=uuid4(), link_id=link_id, clicked_at=datetime.now(UTC), device=device)


async def publish_click(redis: Redis, event: ClickEvent) -> None:
    """Add the event to the Stream. A lost click is logged but never an error:
    the visitor must still reach their destination."""
    try:
        # One field holding the whole event as JSON keeps the message format
        # in a single place (the model above).
        await redis.xadd(CLICKS_STREAM, {"data": event.model_dump_json()})
    except RedisError:
        logger.warning(
            "Could not publish click on link %s; the click is not counted", event.link_id
        )
