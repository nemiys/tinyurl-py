# ADR-0007: Redirect with 302, never cached

## Status
Accepted

## Context
Redirecting is the product, and four features depend on every click reaching
the server: counting it, honouring an expiry, honouring a deletion, and picking a
destination by device.

## Decision
Answer `302 Found` with `Cache-Control: no-store`.

- `301 Moved Permanently` tells browsers "this address has moved for good,
  remember it". After the first visit a browser would go straight to the
  destination and never ask us again: no click counted, and a link that expired
  or was deleted would keep working for that visitor.
- `302` means "temporarily elsewhere, ask again next time", so every click
  returns to us. `no-store` also stops browsers and proxies from remembering the
  answer, since some cache a 302 anyway.

Other answers of the redirect: `404` for a code that does not exist or was
deleted, `410 Gone` for an expired link (it did exist), `429` over the rate
limit. The mobile rule picks the destination from the `User-Agent` header
(a phone is recognised by "Mobi").

## Alternatives considered
- **301 / 308 (permanent)**: faster for repeat visitors, and passes search
  ranking along, but defeats counting, expiry and deletion. Search ranking is not
  a goal of a short link.
- **303 / 307**: differ from 302 in how the request method is treated; for
  `GET` links there is no practical difference.
- **An HTML page or JavaScript redirect**: slower, and does not work for
  crawlers and command-line clients.

## Consequences
- Every click is a request to our server. The Redis cache (ADR-0010) is what makes
  that cheap, and recording the click happens after the response (ADR-0001).
- Reading the device from `User-Agent` is a convenience, not a guarantee: the
  header can be missing or faked, and a wrong guess only sends a visitor to the
  normal address.
