"""Rules for creating a link: which URLs and which expiry dates are accepted."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from tinyurl_py.api.schemas import CreateLinkRequest, LinkPublic

SOON = datetime.now(UTC) + timedelta(days=1)


def test_a_plain_https_url_is_accepted() -> None:
    request = CreateLinkRequest(url="https://example.com/page")

    assert str(request.url) == "https://example.com/page"
    assert request.mobile_url is None
    assert request.expires_at is None


@pytest.mark.parametrize(
    "bad_url",
    [
        "ftp://example.com/file",
        "javascript:alert(1)",  # would run code in the visitor's browser
        "data:text/html,<script>alert(1)</script>",
        "example.com/page",  # no scheme
        "not a url at all",
        "https://example.com/" + "a" * 2100,  # longer than browsers accept
    ],
)
def test_urls_that_are_unsafe_or_malformed_are_rejected(bad_url: str) -> None:
    with pytest.raises(ValidationError):
        CreateLinkRequest(url=bad_url)


def test_mobile_url_follows_the_same_rules() -> None:
    accepted = CreateLinkRequest(url="https://example.com", mobile_url="https://m.example.com")

    assert str(accepted.mobile_url) == "https://m.example.com/"
    with pytest.raises(ValidationError):
        CreateLinkRequest(url="https://example.com", mobile_url="javascript:alert(1)")


def test_expiry_in_the_future_with_a_timezone_is_accepted() -> None:
    request = CreateLinkRequest(url="https://example.com", expires_at=SOON)

    assert request.expires_at == SOON


def test_expiry_in_the_past_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CreateLinkRequest(
            url="https://example.com", expires_at=datetime.now(UTC) - timedelta(hours=1)
        )


def test_expiry_without_a_timezone_is_rejected() -> None:
    # "10:00" alone is ambiguous: whose 10:00?
    naive = datetime.now() + timedelta(days=1)  # no tzinfo, on purpose

    with pytest.raises(ValidationError):
        CreateLinkRequest(url="https://example.com", expires_at=naive)


def test_public_link_has_exactly_the_documented_fields() -> None:
    assert set(LinkPublic.model_fields) == {
        "code",
        "short_url",
        "url",
        "mobile_url",
        "expires_at",
        "created_at",
    }
