"""Which destinations a short link may point to."""

import pytest
from tinyurl_py.domain.urls import check_destination, is_public_host

from tinyurl_py.domain import urls
from tinyurl_py.settings import settings


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "LOCALHOST",
        "localhost.",  # a trailing dot is still the same name
        "app.localhost",
        "127.0.0.1",
        "127.9.9.9",
        "0.0.0.0",
        "10.0.0.5",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",  # cloud metadata service: hands out credentials
        "100.64.0.1",  # carrier-grade NAT
        "[::1]",
        "::1",
        "fe80::1",
        "fc00::1",
        "[::ffff:7f00:1]",  # 127.0.0.1 wearing an IPv6 coat
        "printer.local",
        "db.internal",
        "nas.lan",
        "host.localdomain",
        "intranet",  # a single word only means something inside a private network
        "",
    ],
)
def test_internal_hosts_are_not_public(host: str) -> None:
    assert not is_public_host(host)


@pytest.mark.parametrize(
    "host",
    [
        "example.com",
        "sub.example.co.uk",
        "xn--e1afmkfd.xn--p1ai",
        "8.8.8.8",
        "[2606:4700:4700::1111]",
    ],
)
def test_ordinary_hosts_are_public(host: str) -> None:
    assert is_public_host(host)


def fake_dns(monkeypatch: pytest.MonkeyPatch, answers: dict[str, list[str]]) -> None:
    async def resolve(host: str) -> list[str]:
        if host not in answers:
            raise OSError("no such host")
        return answers[host]

    monkeypatch.setattr(urls, "resolve_host", resolve)


async def test_a_name_that_points_to_an_internal_address_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_dns(
        monkeypatch,
        {"evil.example.net": ["127.0.0.1"], "mixed.example.net": ["93.184.216.34", "10.0.0.1"]},
    )

    assert await check_destination("evil.example.net") is not None
    assert await check_destination("mixed.example.net") is not None  # one bad address is enough


async def test_a_name_that_points_to_a_public_address_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_dns(monkeypatch, {"good.example.org": ["93.184.216.34", "2606:2800:220:1::1"]})

    assert await check_destination("good.example.org") is None


async def test_a_name_that_cannot_be_resolved_is_not_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fail open: a typo or a DNS hiccup should not stop link creation. The
    # service only redirects, it never fetches the address itself.
    fake_dns(monkeypatch, {})

    assert await check_destination("not-yet-live.example.org") is None


async def test_an_ip_literal_needs_no_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def must_not_be_called(host: str) -> list[str]:
        raise AssertionError("no lookup is needed for an IP address")

    monkeypatch.setattr(urls, "resolve_host", must_not_be_called)

    assert await check_destination("10.0.0.5") is not None
    assert await check_destination("8.8.8.8") is None


async def test_a_link_to_the_service_itself_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    # Otherwise somebody could create a short link that redirects to a short
    # link that redirects to ... a loop that only wastes requests.
    monkeypatch.setattr(settings, "base_url", "https://sho.rt")
    fake_dns(monkeypatch, {"sho.rt": ["93.184.216.34"], "sho.rt.evil.com": ["93.184.216.35"]})

    assert await check_destination("sho.rt") is not None
    assert await check_destination("sho.rt.evil.com") is None  # merely looks similar
