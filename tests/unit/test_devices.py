"""Telling phones from everything else by the User-Agent header."""

import pytest

from tinyurl_py.domain.devices import is_mobile

IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
ANDROID_PHONE = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36"
)
WINDOWS_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
IPAD = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)


@pytest.mark.parametrize(
    ("user_agent", "expected"),
    [
        (IPHONE, True),
        (ANDROID_PHONE, True),
        (WINDOWS_DESKTOP, False),
        (IPAD, False),  # iPads present themselves as desktops: "mobile" means phone here
        ("", False),
        (None, False),  # a request may have no User-Agent at all
    ],
)
def test_only_phones_count_as_mobile(user_agent: str | None, expected: bool) -> None:
    assert is_mobile(user_agent) is expected
