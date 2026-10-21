# ADR-0006: Random short codes, made unique by an index

## Status
Accepted

## Context
Every link needs a short code that is unique, short enough to share, and not
guessable: if codes were predictable, anyone could walk through everyone else's
links. Uniqueness must hold when requests arrive simultaneously and when the
application runs as several processes.

## Decision
A code is 7 characters from 62 (`a-z`, `A-Z`, `0-9`), about 3.5 trillion
possibilities, drawn with the `secrets` module (the operating system's secure
randomness; plain `random` follows a formula that can be reconstructed from
observed codes).

Uniqueness is decided by the database, not by our code: generate a code, insert
it, and the unique index on `code` refuses a duplicate. On `DuplicateKeyError`
generate another, up to 5 attempts, then answer `503` with `Retry-After`. There is
no "is this code free?" query first, because the answer could be stale by the
time of the write.

The redirect rejects anything that cannot be one of our codes (wrong length or
characters) before touching Redis or Mongo, so paths such as `/favicon.ico` cost
nothing.

## Alternatives considered
- **A counter encoded in base62**: no collisions at all and shorter codes at
  first, but sequential codes are enumerable (`/aaaaaab`, `/aaaaaac`, ...) and a
  single counter is a point of coordination between processes.
- **A hash of the URL**: the same URL always gets the same code, which is wrong
  for per-user links with their own statistics and expiry, and truncated hashes
  collide anyway.
- **A pool of pre-generated codes**: removes the retry path but adds a service
  to run and fill, for a problem that almost never happens.
- **Longer codes (UUIDs)**: unambiguous but not "short".
- **Check first, then insert**: has a race and so can hand the same code to two
  links.

## Consequences
- A collision is possible but very rare: with a million links, a new code
  collides with probability about 3 in ten million, and five collisions in a row
  would mean the generator itself is broken. That is why the failure is a `503`.
- Codes carry no meaning and no order.
- A deleted link keeps its row (ADR-0008), so its code is never handed out again.
- If the code length ever changes, `is_valid_code` and the tests change with it.
