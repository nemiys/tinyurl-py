# ADR-0009: Authentication with argon2 passwords and signed tokens

## Status
Accepted

## Context
Links belong to users, so the API must know who is asking and protect each
person's links from everyone else. Passwords must survive a stolen database, and
the scheme should stay stateless enough not to need a session store.

## Decision
**Passwords** are hashed with argon2 (through `pwdlib`), with a random salt and a
deliberately slow cost (tens of milliseconds). Only the hash is stored. The hash
string records its own parameters, so settings can be tuned later while old
hashes still verify. Hashing runs on a helper thread because it blocks.
Passwords must be 8 to 128 characters (the upper limit keeps a huge input from
being used to burn CPU).

**Login** answers the same `401` for an unknown email and a wrong password. For
an unknown email it still verifies against a throwaway hash, so both cases take the
same time and the timing does not reveal which emails are registered. Attempts are
rate limited per IP (ADR-0003).

**Tokens** are JWTs signed with HS256: claims `sub` (user id), `iat`, `exp`;
lifetime 60 minutes. The token is signed, not encrypted: nothing private goes in
it. Verification names the allowed algorithm itself instead of trusting the
token's header (the classic "alg" attack) and requires `exp` and `sub`.
`JWT_SECRET` has no default value: the application refuses to start without one,
because a key that anyone reading the repository knows would let anyone forge
logins. It must also be at least 32 characters (256 bits, the key size HS256
calls for); an empty or short value stops the start just the same, rather than
letting the app run and fail on every login. Every request also checks that
the user still exists, so the token of a deleted account stops working at once.

**Authorisation** is part of the query, not a check after it: link lookups filter
on code **and** owner, so someone else's link answers `404`, exactly like a code
that does not exist. Answering `403` would confirm that the code exists.

## Alternatives considered
- **Server-side sessions in Redis**: can be revoked instantly, but every request
  needs a lookup and the session store becomes something to keep alive.
- **bcrypt or PBKDF2**: acceptable, but argon2 is the current recommendation and
  resists GPU cracking better.
- **RS256 (asymmetric keys)**: right when other services must verify tokens
  without being able to create them. There is one service here, so one shared
  secret is simpler.
- **A third-party identity provider**: the better answer for a real product, and
  out of scope for showing the fundamentals.

## Consequences
- No logout and no revocation before expiry: a stolen token works until it
  expires. Short lifetimes limit that; refresh tokens or a denylist would be the
  next step.
- Rotating `JWT_SECRET` logs everybody out.
- In the Docker demo a random secret is made for each run when none is given, so
  logins end when the container restarts (see `docker/entrypoint.sh`).
