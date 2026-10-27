# ADR-0002: Cassandra for clicks, kept forever, one table per query

## Status
Accepted

## Context
Every redirect produces a click. Clicks are written constantly, never edited,
and read in one shape: "the clicks of link X on day Y" (and, summed over days,
the total of link X). Links and users are different: few, edited, and looked
up by several fields, which suits MongoDB.

## Decision
Cassandra holds clicks in one table, `clicks_by_link_day`:

- **Partition key `(link_id, day)`**: all clicks of one link on one day live
  together, so the common question reads a single partition. Adding the day
  keeps a very popular link from growing one endless partition.
- **Clustering columns `(clicked_at DESC, event_id ASC)`**: newest first
  inside a partition; `event_id` tells apart clicks of the same millisecond.
- **Idempotent writes**: the whole primary key comes from the event itself
  (`event_id` and `clicked_at` are set when the click happens, not by the
  worker). A redelivered event overwrites its own row, so at-least-once
  delivery never double counts.
- **Total clicks of a link** are computed on read, by summing the days since
  the link was created. No counters: `counter` columns add `+1`, and a
  redelivered message would add it twice.
- **Retention: forever.** Statistics are the product, and a link's total must
  not shrink as time passes.

## Alternatives considered
- **A TTL on every row (`USING TTL`, for example one year)**: Cassandra
  deletes expired rows by itself, which bounds the table size at no code
  cost. Rejected for now because the "total clicks" of an old link would
  decrease over time. It fits raw log-style data well, and it is the first
  thing to reach for when volume becomes large: keep raw rows for a limited
  time and keep a small daily summary table forever.
- **Daily summary table, written by the worker**: makes totals cheap, but
  needs its own idempotency story. Deferred until reading many days becomes
  slow; see Consequences for what that costs today and how it would be added.
- **MongoDB for clicks**: possible at this size, but one document per click
  with a constant write stream is the workload Cassandra is built for, and
  the project is meant to show each store used for what it is good at.
- **A second table `clicks_by_user_day`**: Cassandra tables are designed per
  query. If "all clicks of all my links" is ever needed, that is a second
  table written by the same worker.

## Consequences
The table only answers the question it was designed for. Any new question
(for example by country or by hour across all links) means a new table, not a
new `WHERE`. The table grows without bound until a summary table or a TTL is
introduced. At this project's volume that is acceptable.

**Statistics get slower as a link ages.** One request for statistics runs one
count per day since the link was created, whatever `days` asks to list, because
the total covers the link's whole life: a year-old link costs 365 queries (eight
at a time). And `count(*)` is not a stored number; it reads every row of the
partition, so the cost also grows with the clicks of each day. Fine for links
weeks or months old with modest traffic; this is the first place to change if
either grows.

The change, when needed: once a day is over, count its partition once and store
the number in a table `daily_clicks` (partition key `link_id`, clustering `day`).
A finished day never changes, so counting it again writes the same number over
the same row: idempotent, unlike a `+1` counter. The total becomes one read of
`daily_clicks` plus a count of today, two queries however old the link is.
