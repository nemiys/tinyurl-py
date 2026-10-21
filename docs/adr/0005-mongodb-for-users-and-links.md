# ADR-0005: MongoDB for users and links

## Status
Accepted

## Context
Users and links are the system's source of truth. They are few compared with
clicks, edited from time to time, looked up by a handful of fields (email, code,
owner), and one invariant matters above all: **an email and a short code each
exist at most once**, even when two requests arrive in the same instant.

A link is also the natural place for "smart" behaviour. Today that is an
optional mobile address and an optional expiry; later it could be a list of
rules. Those are optional, nested and likely to grow.

## Decision
MongoDB, through PyMongo's native async client (`AsyncMongoClient`; `motor` is
being retired in its favour).

- `users`: `email` (stored lowercase), `password_hash`, `created_at`.
  Unique index on `email`.
- `links`: `code`, `owner_id`, `url`, `mobile_url`, `expires_at`, `created_at`,
  `deleted_at`. Unique index on `code`, and a compound index
  `(owner_id, created_at desc, _id desc)` that serves "my links, newest first".
- Uniqueness is enforced by the unique indexes, never by "look, then write":
  between the look and the write someone else could take the value. We write, and a
  `DuplicateKeyError` means someone had it.
- The indexes are created when the application starts (and the application
  refuses to start without Mongo): better than running without the indexes that
  protect the data. No migration tool; the set of indexes is small.

## Alternatives considered
- **PostgreSQL**: would work equally well at this size, and users plus links are
  relational enough. Not chosen because the sibling project `wikiguard-py` already
  shows PostgreSQL, and here a document store has a real use: optional fields
  and rule-like data that grows without a schema migration for each addition.
- **Cassandra for links**: it is used for clicks, where it fits. For links it
  would be a poor fit: lookups by several fields would need several tables, and
  a uniqueness guarantee needs lightweight transactions, which are slow and
  awkward.
- **Redis as the only store**: fast, but a cache and queue is not a source of
  truth; losing it must never lose a link.

## Consequences
- No joins and no multi-document transactions are needed by the current design.
  If a feature needed them (for example moving links between users atomically),
  this decision would be worth revisiting.
- Mongo's `ObjectId` is the link's permanent identity (`link_id` in click
  events); the short code is only its public alias.
- Local and CI runs need a Mongo that starts. MongoDB 8 refuses to start on Linux
  kernels 6.19 to 7.0.13, which is why CI is pinned to `ubuntu-22.04` for now.
