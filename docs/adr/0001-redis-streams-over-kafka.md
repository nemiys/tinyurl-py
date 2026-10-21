# ADR-0001: Redis Streams, not Kafka, for click events

## Status
Accepted

## Context
Every redirect must answer fast, so recording the click cannot happen inside
the request. The API publishes a small "click happened" event and a separate
worker consumes it and writes the click to Cassandra. Some durable queue is
needed between the two: the API must never block on the slow write, and a
worker crash must not lose events.

The sibling project `wikiguard-py` solves the same shape of problem with
Kafka (see its ADR-0002), where Kafka was chosen on purpose as the thing to
learn. Here the goal is different.

## Decision
Redis Streams (via `redis.asyncio`), read by a consumer group. The worker
acknowledges an event only after it has been written to Cassandra, so a crash
leads to redelivery (at-least-once), never to loss. Each event gets its `event_id`
(a random UUID) and its time when the click happens, in the API, before it enters
the queue; the Cassandra primary key includes both, so a redelivered event
overwrites the same row instead of creating a duplicate. A message that waits too
long with a worker that died is taken over by another one (`XAUTOCLAIM`), and a
message that can never be read is logged and dropped so it cannot block the queue.
After a message is acknowledged it is also deleted from the stream.

## Alternatives considered
- **Kafka**: built for far higher volume, with partitions, long retention
  and replay. Rejected because the expected click volume does not need it, it
  adds a broker to run and explain, and Redis is already part of the system
  (redirect cache, rate limiting), so Streams add no new infrastructure.
- **Write to Cassandra directly in the request**: simplest, but puts a
  database write on the critical path of every redirect and loses clicks if
  the write fails.
- **In-process `asyncio.Queue`**: not durable; a crash loses everything in
  the queue, and it cannot be shared by several worker processes.

## Consequences
Streams live mostly in memory. Because the worker deletes what it has handled, the
stream holds only what is still waiting (a length cap would instead delete unhandled
events when the worker is down for long). Its length is the number of clicks not yet
counted, which is worth watching. Throughput and retention are lower than Kafka's. If
click volume grew by orders of magnitude, moving to Kafka would be the next
step; the producer/consumer shape and the `event_id` idempotency would stay
the same.
