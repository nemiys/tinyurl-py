"""How long a link may stay in the cache."""

from datetime import UTC, datetime, timedelta

from tinyurl_py.cache.links import DEFAULT_TTL_SECONDS, cache_ttl_seconds

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)


def test_default_ttl_is_one_hour() -> None:
    assert DEFAULT_TTL_SECONDS == 3600


def test_link_without_expiry_gets_the_default_ttl() -> None:
    assert cache_ttl_seconds(None, now=NOW) == DEFAULT_TTL_SECONDS


def test_link_expiring_soon_is_cached_only_until_it_expires() -> None:
    assert cache_ttl_seconds(NOW + timedelta(minutes=10), now=NOW) == 600


def test_link_expiring_far_away_gets_the_default_ttl() -> None:
    assert cache_ttl_seconds(NOW + timedelta(days=5), now=NOW) == DEFAULT_TTL_SECONDS


def test_already_expired_link_gets_no_ttl() -> None:
    assert cache_ttl_seconds(NOW - timedelta(seconds=1), now=NOW) == 0
