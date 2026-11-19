# ADR-0003: Sliding-window rate limiting in Redis

## Status
Accepted

## Context
Four endpoints invite abuse: creating links (a script can mint millions),
redirects (code guessing is a stream of requests for unknown codes, each one
costing a Mongo lookup), login (password guessing) and registration (each
sign-up is an argon2 hash, and every new account brings a fresh allowance for
creating links). Each needs a cap on
requests per time, a clear "too many requests" answer, and a hint for
well-behaved clients about when to come back.

## Decision
A sliding window kept in Redis: "at most N requests in any window of W
seconds ending now". Each key holds a sorted set; a request is a member (unique
id) scored with its time. A small Lua script removes expired members, counts
what is left and either records the request or refuses it. Redis runs the script
as one uninterruptible step, so two simultaneous requests cannot both take the
last place.

| What | Key | Default |
|---|---|---|
| Creating links | the logged-in user | 20 per minute |
| Redirect | client IP | 120 per minute |
| Login | client IP | 10 per minute |
| Registration | client IP | 10 per hour |

All values are settings. A refusal is `429` with `Retry-After`, the number of
seconds until the oldest counted request leaves the window, rounded up.

Details that matter:
- **A refused request is not recorded.** Otherwise whoever keeps hammering
  would extend their own block forever.
- **Redirect junk paths are not counted.** The format check (`is_valid_code`)
  runs first and costs nothing; well-formed but unknown codes are counted,
  which is what slows guessing. Login and registration are limited before the
  password is hashed or checked, so a flood does not also load the CPU with
  argon2. They use separate keys, so neither allowance uses up the other.
- **Fail open.** If Redis is unreachable the limiter allows the request and logs a
  warning. Consistent with the cache and the click queue: Redis problems must
  not become outages of the redirect.
- **Client IP is the address of the connection**, never read from
  `X-Forwarded-For` by our code, because any client can send that header and
  pick a new "address" per request. Behind a proxy, run uvicorn with
  `--forwarded-allow-ips` set to the proxy: it then substitutes the real address
  only for requests that come from that trusted proxy. Uvicorn trusts
  `127.0.0.1` by default, so a client connecting from the same machine CAN
  choose its address with that header (seen while testing locally; with
  `--no-proxy-headers` the same request is limited). Harmless where only the
  proxy can reach the app, and the reason to set the trusted list explicitly.
- **Time comes from the application** (an injected clock) rather than from
  Redis, which keeps the limiter testable without sleeping.

## Alternatives considered
- **Fixed window counter** (`INCR` + `EXPIRE`): simplest and cheapest, but resets
  on the clock, so 10 requests just before the boundary and 10 just after pass
  as 20 within seconds. The exact weakness a sliding window removes.
- **Sliding window counter** (two fixed windows, weighted): constant memory per
  key, but only approximate. Our limits are small, so keeping every request
  (memory is proportional to the limit, at most 120 entries per key) is cheap
  and exact.
- **Token bucket**: allows controlled bursts and is the usual choice for APIs
  that want smooth throughput. Our goal is a hard ceiling per window, which the
  sliding window states directly.
- **Fail closed**: never weaker protection, but a Redis hiccup would stop every
  redirect. Right for protecting a bank login, wrong for a link shortener.
- **Limit at a gateway (nginx, cloud WAF)**: the better place in production and
  worth adding there too. In the app it keeps the behaviour visible, testable
  and independent of how it is deployed.

## Consequences
- Every redirect makes one more Redis round trip (about a millisecond).
- Per-IP limits hit people who share an address (an office, a school), hence
  the generous 120 per minute. Attackers with many addresses get around IP
  limits; login could additionally be limited per account at the price of
  letting an attacker lock a victim out. Not done.
- With several API servers, slightly different clocks blur the window by that
  difference. Moving the clock into the Lua script (`TIME`) would remove it.
