# ADR-0008: Deleting a link marks it, it does not remove it

## Status
Accepted

## Context
When a user deletes a link, the link must stop working at once. But its click
statistics are the user's data and should stay readable. The statistics live in
Cassandra under the link's identity; finding them again needs the link's row
(for its owner and the day it was created). And a short code must not be given
to a different link later, or old clicks would mix with new ones.

## Decision
Soft delete: `DELETE /links/{code}` sets `deleted_at` on the row instead of
removing it.

- The redirect, `GET /links/{code}`, the listing and a second `DELETE` all ignore
  links with `deleted_at` set, so to everyone they answer `404`, as if it never
  existed. (A missing field counts as "not deleted".)
- The statistics endpoint deliberately does not filter on it, and reports
  `deleted: true`, so the numbers of a deleted link remain reachable by its owner.
- The row keeps occupying the unique index, so the code cannot be reused.
- The cached copy in Redis is replaced by a short-lived tombstone right after the
  row is marked, and only after: clearing the cache first would let a click in
  between copy the link straight back from Mongo. The tombstone also stops a click
  that read the link just before the delete from caching it just after (ADR-0010). If Redis is down at that moment the delete still
  succeeds and the copy expires on its own within the cache time limit (ADR-0010).

## Alternatives considered
- **Removing the row**: simplest, but the statistics become unreachable (nothing
  says whose they are) and the code could be reissued.
- **Moving the row to an archive collection**: keeps the data but the code could
  still be reissued unless the archive is also checked on every creation.
- **Deleting the clicks together with the link**: needs a pass over every day
  since creation and makes deleting depend on Cassandra being up.

## Consequences
- Deleted links stay in the database forever. If that ever conflicts with a
  requirement to erase data, a periodic purge (for example a Mongo TTL index on
  `deleted_at`, plus removing the clicks) is the follow-up.
- Every query on links must remember the `deleted_at` condition; the tests of
  each endpoint cover it.
