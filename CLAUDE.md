# tinyurl-py

A URL shortener with **smart links** (a different destination for mobile visitors, an expiry date) and click statistics. A Python rewrite and upgrade of a course project (`nemiys-tinyurl`, Java/Spring).

The point of the project is to show sound backend fundamentals (REST, auth, uniform errors, tests, CI) and reasoned system design: which data store holds what, where the cache sits, and how recording a click avoids slowing the redirect. Small, clean and documented beats wide and fragile.

## Architecture

```
client ──► FastAPI ──► Redis (cache code→target, rate limits, click Stream)
              │              │
              ▼              ▼
           MongoDB      worker ──► Cassandra (clicks)
   (users, smart links)
```

- **MongoDB**: users and links; the source of truth for links. A unique index on the short code guarantees uniqueness.
- **Redis**: cache (not a source of truth, so never what guarantees uniqueness), sliding-window rate limiting, and a Stream of click events.
- **Cassandra**: one table of clicks. Partition key `(link_id, day)`, clustering `clicked_at, event_id`. Writing the same key again overwrites, so a message delivered twice does not create a duplicate.
- **Redirect**: look in Redis, else in Mongo and fill the cache; answer 302. Publishing the click event happens after the response and never blocks it.
- **Worker**: a separate process. Reads the Stream through a consumer group, writes to Cassandra, and acknowledges only after the write (at-least-once; recovers pending and abandoned messages).

Every significant decision is explained in `docs/adr/`.

## Stack and ports

Python 3.12, `uv`, FastAPI (async), `pydantic-settings`, `pymongo` async (`AsyncMongoClient`), `cassandra-driver`, `redis` async, `pwdlib` (argon2), `PyJWT`. Tests: `pytest`, `pytest-asyncio`, `httpx`, `pytest-cov`. Quality: `ruff`, `mypy` (strict). A new dependency needs a one-line reason.

Host ports (deliberately not the defaults, so it can run next to other projects): Redis 6381, Mongo 27018, Cassandra 9043, API 8001.

## Layout

```
src/tinyurl_py/
  api/          routers, schemas, dependencies, error handlers
  domain/       pure logic: codes, device detection, destination rules
  security/     passwords, tokens, rate limiter
  cache/        the Redis link cache
  events/       click event model and publishing
  persistence/  Mongo, Redis, Cassandra connections and the click store
  worker/       the Stream consumer and its entry point
cassandra/      schema.cql, applied by the cassandra-init service
docs/adr/       architecture decision records
tests/          unit/ and integration/ (integration needs docker compose)
```

## Run locally

Everything in containers (the API at http://localhost:8001/docs, plus the worker that counts clicks):

```
docker compose up --build
```

For development, with the databases in containers and the code on your machine:

```
docker compose up -d --wait redis mongo cassandra cassandra-init
uv sync
uv run pytest --cov
uv run uvicorn tinyurl_py.main:app --port 8001
uv run python -m tinyurl_py.worker
```

Configuration is read from environment variables or a git-ignored `.env`; copy `.env.example` and set `JWT_SECRET`. Inside Docker, a random `JWT_SECRET` is generated per run when none is given (logins end on restart).

## Conventions

- Conventional commit prefixes: `feat:` `fix:` `test:` `docs:` `chore:` `ci:`; one small commit per logical step.
- New behaviour starts with a failing test, committed before the code. A bug starts with a test that reproduces it.
- No secrets in code or history; `.env.example` only.
- Errors always have the shape `{"error": {"code", "message", "details"?}}`.
- `ruff check`, `ruff format --check`, `mypy src tests` and the tests (coverage at least 95%) must pass; CI runs all of them.
- Code and comments in English.

## Known temporary workarounds

- `pyasyncore` is installed because `cassandra-driver` 3.30.1 still imports the `asyncore` module that Python 3.12 removed. Remove it when the driver stops needing it.
- CI is pinned to `ubuntu-22.04`: MongoDB refuses to start on Linux kernels 6.19 to 7.0.13, which `ubuntu-latest` moved to. Revisit when MongoDB or the runner image is fixed.

## Acceptance

`docker compose up` brings everything up. The full flow works: register, create a link, click it, see the click in the statistics. Stop the worker, click 10 times, start it: exactly 10 clicks. Too many requests answer 429, and an internal address is refused. CI is green.
