"""MongoDB connection helpers.

Uses PyMongo's native async client (`AsyncMongoClient`); the older `motor`
package is being retired in its favour.
"""

from typing import Any

from pymongo import AsyncMongoClient

from tinyurl_py.settings import settings

DATABASE_NAME = "tinyurl"

# A Mongo document is a dict of field name -> value.
type Client = AsyncMongoClient[dict[str, Any]]


def create_client() -> Client:
    # One client per process is enough: it keeps its own pool of connections
    # and is safe to share, so the app creates it once at startup.
    return AsyncMongoClient(settings.mongo_url)
