# ADR-0011: Offset pagination, and no free-text search

## Status
Accepted

## Context
A user lists their own links. The list can grow, so it must come in pages, and
an endpoint that can return "everything" is a way to make one request expensive.
A list of links also needs filtering and ordering.

## Decision
`GET /links` takes `limit` (1 to 100, default 20) and `offset` (0 or more). The
answer carries the page and what a client needs to draw "page 3 of 12":

```
{"items": [...], "total": 87, "limit": 20, "offset": 40}
```

- Out-of-range values are a `422`, so nobody can ask for a million rows.
- `status` filters (`all`, `active`, `expired`; a link with no expiry counts as
  active) and `order` (`asc` or `desc` by creation time). Both are closed lists,
  so no arbitrary word reaches a query. `total` counts only what matches the
  filter.
- The order is by creation time and then by `_id`. The second key breaks ties:
  without it, two links created in the same moment could swap places between
  requests, and a link could show up on two pages or on none. A compound index
  `(owner_id, created_at, _id)` serves the query in both directions.
- **No free-text search.** Deliberately left out, and listed as a future
  extension: a user's list is short, and substring matching cannot use an
  ordinary index.

## Alternatives considered
- **Cursor ("keyset") pagination**: "give me what comes after this one". Stays fast
  however deep you go and is stable while rows are added. Better for large or
  fast-changing lists. Offset costs more the larger it gets, which is irrelevant
  for one person's links, and it is simpler for a client to jump to page N.
- **Plain list with no total**: simplest, but the client cannot show page numbers
  and the format cannot grow without breaking clients.
- **Search by regular expression**: scans every one of the user's links, needs
  escaping of user input, and adds little for a short list. A text index or a
  search engine would be the way if it were ever needed.

## Consequences
- Counting costs one extra query per page; the index keeps it cheap.
- With many thousands of links per user, or links being added while someone pages
  through, move to cursors.
- Sorting by number of clicks is not offered: clicks live in Cassandra, and the
  list is a Mongo query.
