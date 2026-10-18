"""MongoDB connection helpers.

Uses PyMongo's native async client (`AsyncMongoClient`); the older `motor`
package is being retired in its favour.
"""

from typing import Any

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from tinyurl_py.settings import settings

DATABASE_NAME = "tinyurl"

# A Mongo document is a dict of field name -> value.
type Client = AsyncMongoClient[dict[str, Any]]


def create_client() -> Client:
    # One client per process is enough: it keeps its own pool of connections
    # and is safe to share, so the app creates it once at startup.
    # By default the driver waits 30s for a reachable server before giving
    # up, which would make a "Mongo is down" answer painfully slow.
    return AsyncMongoClient(settings.mongo_url, serverSelectionTimeoutMS=2000)


async def ensure_indexes(db: AsyncDatabase[dict[str, Any]]) -> None:
    """Create the indexes the app relies on. Safe to run on every startup:
    if an index already exists, Mongo leaves it alone."""
    # Unique indexes are what really guarantee "one account per email" and
    # "one link per code", even when two requests arrive at the same moment.
    await db.users.create_index("email", unique=True)
    await db.links.create_index("code", unique=True)
    # Serves "my links, newest first": filter by owner, already sorted by date.
    await db.links.create_index([("owner_id", ASCENDING), ("created_at", DESCENDING)])
