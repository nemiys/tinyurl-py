# ADR-0004: One error format, and only public destinations

## Status
Accepted

## Context
Errors came out in three shapes: our own `{"detail": "text"}`, FastAPI's
validation list, and a bare text 500. A client would need three code paths, and
the validation error echoed the rejected input (which can be a password).

Separately, a short link could point anywhere that parses as http(s), including
`http://localhost/...` and `http://169.254.169.254/...` (the metadata address
where cloud servers hand out credentials). Our service only redirects and never
fetches the address, so the direct risk is small, but such links are a way to
disguise an attack on a victim's own machine or network, and would become a real
SSRF hole the day a link preview or a health check of destinations is added.

## Decision
**Errors.** Every response that is an error has the form
`{"error": {"code", "message", "details"?}}`, produced by three handlers: for
HTTP errors (including the framework's own 404 and 405), for request validation,
and for anything unexpected.
- `code` is a stable word (`not_found`, `rate_limited`, `unsafe_destination`...)
  derived from the status, or chosen by the code that raises the error.
- Headers set by the raiser survive (`Retry-After`, `WWW-Authenticate`).
- Validation errors list `field` and `message` only, never the input.
- Unexpected errors answer a fixed `500 internal_error` with no detail; the
  traceback goes to the log.

**Destinations.** Checked when a link is created, for `url` and `mobile_url`:
1. The host must be public: not loopback, private, link-local, carrier-grade
   NAT, reserved or documentation ranges; not `localhost`, `*.local`,
   `*.internal` and similar; not a single-word name. IPv6 forms that wrap an
   IPv4 address are unwrapped first. (The URL parser already turns
   `2130706433` or `0x7f.1` into `127.0.0.1`, so one check covers those.)
2. It must not be this service's own host (a redirect loop).
3. A name is resolved with DNS (2 s timeout); if any address it points to is
   not public, it is refused. If the name cannot be resolved the link is
   accepted: a typo or a DNS hiccup must not stop link creation.

## Alternatives considered
- **RFC 7807 `application/problem+json`**: a standard shape, widely understood.
  Our own small shape carries what a client needs, with a code to switch on;
  moving to problem+json later would only change the handlers.
- **Reject names that do not resolve**: stricter, but turns every DNS outage
  into a creation outage and refuses domains that are about to go live.
- **Only a text check, no DNS**: misses `evil.example.net -> 127.0.0.1`.
- **Re-check on every redirect**: would catch DNS that changes after creation
  ("DNS rebinding"), at the cost of a lookup on the hot path. Not needed while
  the service never fetches destinations itself.

## Consequences
- A name can point somewhere public at creation time and somewhere internal
  later. Acceptable now; a feature that fetches destinations would have to
  check again at fetch time, on the address it actually connects to.
- Link creation now makes up to two DNS lookups. It is rate limited (ADR-0003),
  and lookups are bounded by the timeout.
- Existing clients that read `detail` must read `error.message` instead.
