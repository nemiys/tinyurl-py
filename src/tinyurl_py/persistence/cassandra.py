"""Cassandra connection helpers.

`cassandra-driver` is a blocking library: its calls wait for the answer and
would freeze our async server meanwhile. So every call here goes through
`asyncio.to_thread`, which runs it on a helper thread and lets the server keep
handling other requests. Simple, and plenty for our volume.
"""

import asyncio

from cassandra.cluster import Cluster, Session

from tinyurl_py.settings import settings

# Created by cassandra/schema.cql (the `cassandra-init` service).
KEYSPACE = "tinyurl"


async def connect() -> Session:
    # Cassandra 5 speaks protocol 5. Without saying so the driver first tries a
    # newer one, fails, and logs two "downgrading" warnings on every start.
    cluster = Cluster([settings.cassandra_host], port=settings.cassandra_port, protocol_version=5)
    # Connecting with a keyspace means queries can say `clicks_by_link_day`
    # instead of `tinyurl.clicks_by_link_day`.
    return await asyncio.to_thread(cluster.connect, KEYSPACE)


async def close(session: Session) -> None:
    # A session belongs to a cluster object; shutting the cluster down closes
    # every connection it opened.
    await asyncio.to_thread(session.cluster.shutdown)
