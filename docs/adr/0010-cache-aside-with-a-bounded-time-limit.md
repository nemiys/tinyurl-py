# ADR-0010: Cache-aside in Redis, with a time limit that never outlives the link

## Status
Accepted

## Context
A redirect happens far more often than anything else, and every one of them
needs the link's destination. Asking MongoDB each time works but is wasteful, and
the redirect should stay quick. Redis is already part of the system.

## Decision
Cache-aside, keyed `link:<code>`:

1. Look in Redis. If found, use it.
2. Otherwise read MongoDB (the source of truth) and store the answer for next time.

The cached value holds only what a redirect needs (link id, destination, mobile
destination, expiry), not the whole document.

- **Time limit**: an entry lives for the shorter of one hour and the time left
  until the link expires, and a link already expired is not cached at all. So the
  cache can never keep redirecting after a link is supposed to be dead. The
  expiry is checked again on every request anyway, cached or not.
- **Redis is never a reason for an error.** If Redis is down, a read is treated
  as a miss and a write is skipped (with a warning); the connection uses short
  timeouts so "down" is noticed in half a second. An entry that cannot be read (an
  old format) is also treated as a miss and is overwritten.
- **Deleting a link replaces its entry with a tombstone** for one minute, right after
  the row is marked deleted (ADR-0008), and a cache write never replaces an existing
  entry (`SET NX`). A redirect that read the link from Mongo just before the deletion
  would otherwise write it back to the cache just after it, and the deleted link would
  keep working for up to the time limit. If Redis is down, the entry expires within
  the time limit.
- **Nothing is cached for codes that do not exist.** Every unknown (but
  well-formed) code goes to Mongo. It is bounded by the format check and the
  per-IP rate limit (ADR-0003) rather than by caching misses.

The cache is not a source of truth and never guarantees uniqueness; the unique index
does (ADR-0006).

## Alternatives considered
- **Write-through** (update the cache whenever a link changes): fresher, but every
  write path must remember it, and a link almost never changes.
- **No cache**: simplest; every click would be a Mongo read.
- **Caching misses (negative caching)**: would cap the cost of code guessing, at
  the price of a delay before a newly created link is found. Left for if guessing
  traffic is ever a real problem.
- **A CDN in front**: would defeat counting clicks (ADR-0007).

## Consequences
- A link edited or deleted can be served stale for up to the time limit if the
  cleanup fails. Links cannot be edited today, and deletion clears the entry.
- Changing the cached format needs no migration: unreadable entries are simply
  refilled.
