"""Which destinations a short link may point to.

Only addresses on the public internet. A short link to `http://localhost/...`
or `http://169.254.169.254/...` (where cloud servers hand out credentials) is a
way to disguise an attack on someone's own machine or network. Our service
only redirects, it never fetches the address, so the direct risk is small; this
keeps it that way even if a link preview is ever added.
"""

import asyncio
import ipaddress
import logging
import socket
from urllib.parse import urlsplit

from tinyurl_py.settings import settings

logger = logging.getLogger(__name__)

# Names that only mean something inside a private network or on one machine.
_INTERNAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".localdomain", ".home.arpa")
DNS_TIMEOUT_SECONDS = 2.0


def _as_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def _ip_is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped  # 127.0.0.1 can hide inside an IPv6 address
    # is_global is False for private, loopback, link-local, reserved, carrier-grade
    # NAT, documentation ranges and so on.
    return ip.is_global


def is_public_host(host: str) -> bool:
    """Judged by the text alone, with no network access."""
    host = host.lower().rstrip(".")  # "localhost." is the same name
    if not host:
        return False
    ip = _as_ip(host)
    if ip is not None:
        return _ip_is_public(ip)
    # A name with no dot ("intranet", "router") only exists inside a private network.
    return "." in host and not host.endswith(_INTERNAL_SUFFIXES)


async def resolve_host(host: str) -> list[str]:
    """All the addresses a name points to. Raises OSError if it points nowhere."""
    loop = asyncio.get_running_loop()
    infos = await asyncio.wait_for(
        loop.getaddrinfo(host, None, type=socket.SOCK_STREAM), DNS_TIMEOUT_SECONDS
    )
    return [str(info[4][0]).split("%")[0] for info in infos]


async def check_destination(host: str) -> str | None:
    """None if `host` is fine, otherwise a short reason it is not."""
    if not is_public_host(host):
        return "points to an internal address"

    own_host = urlsplit(settings.base_url).hostname
    if own_host is not None and host.lower().rstrip(".") == own_host.lower():
        # A short link to a short link: a loop that only wastes requests.
        return "points to this service itself"

    if _as_ip(host) is not None:
        return None  # a public IP address; nothing to look up

    # A public-looking name can still be set up to point at 127.0.0.1.
    try:
        addresses = await resolve_host(host)
    except (OSError, TimeoutError):
        # Fail open: a typo or a DNS hiccup must not stop link creation.
        logger.warning("Could not resolve %s; accepting it unchecked", host)
        return None
    for address in addresses:
        ip = _as_ip(address)
        if ip is not None and not _ip_is_public(ip):
            return "resolves to an internal address"
    return None
