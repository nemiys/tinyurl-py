# Architecture decision records

Each file explains one decision: the situation, what was chosen, what else was
considered, and what it costs.

| # | Decision | In one line |
|---|---|---|
| [0001](0001-redis-streams-over-kafka.md) | Redis Streams, not Kafka, for click events | The queue between the API and the worker, using what is already there |
| [0002](0002-cassandra-for-clicks.md) | Cassandra for clicks | One table per question, idempotent writes, clicks kept forever |
| [0003](0003-sliding-window-rate-limiting.md) | Sliding-window rate limiting | Per user for creating links, per IP for redirects, login and registration |
| [0004](0004-uniform-errors-and-destination-checks.md) | One error format, only public destinations | Stable error codes; no `localhost` or internal addresses |
| [0005](0005-mongodb-for-users-and-links.md) | MongoDB for users and links | Source of truth; unique indexes guarantee uniqueness |
| [0006](0006-random-short-codes-with-a-unique-index.md) | Random short codes | Unguessable, made unique by the database |
| [0007](0007-redirect-with-302.md) | Redirect with 302 | Every click must come back to us |
| [0008](0008-soft-delete-for-links.md) | Soft delete | A deleted link keeps its statistics and its code |
| [0009](0009-authentication-argon2-and-jwt.md) | argon2 passwords and signed tokens | Stateless; other people's links look like they do not exist |
| [0010](0010-cache-aside-with-a-bounded-time-limit.md) | Cache-aside in Redis | A cache that can fail without failing a redirect |
| [0011](0011-offset-pagination-and-no-search.md) | Offset pagination, no search | Limit and offset, a stable order, a closed list of filters |
