"""SSRF guard for the scrape ladder (#13).

The scrape ladder fetches operator/LLM-influenced URLs. Without a guard
the Tier-1 ``httpx`` fetch (``follow_redirects=True``, no allow-list)
would happily retrieve ``http://169.254.169.254/...`` (cloud metadata),
``http://127.0.0.1:.../`` (loopback services) or a public URL that
**redirects** to a private address — the classic SSRF pivot.

:func:`assert_url_allowed` is the single chokepoint: it rejects any
scheme other than http/https, any URL without a host, and any host that
is — or resolves to — a private / loopback / link-local / reserved
address. The caller MUST re-run it on every redirect hop (the ladder
does, with ``follow_redirects=False``).

Residual: this validates the resolved address set but does not pin the
connection to a specific validated IP, so a sub-second DNS-rebind between
validation and connect is still theoretically possible. Closing that
fully needs a custom transport that dials the validated IP with the
original Host/SNI; tracked as a follow-up. The redirect re-validation
here already closes the far more common "public → private redirect"
vector.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlsplit

from iguanatrader.contexts.research.scraping.errors import UnsafeUrlError

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES = frozenset({"http", "https"})


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True if ``ip`` is in any range a scraper must never reach.

    ``is_private`` already covers RFC 1918, IPv6 ULA (fc00::/7) and
    IPv4-mapped private addresses; the rest catch loopback, link-local
    (incl. the 169.254.0.0/16 cloud-metadata range), multicast, reserved
    and the unspecified address.
    """
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _check_addr(host: str, addr: str) -> None:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError as exc:  # pragma: no cover — getaddrinfo returns valid IPs
        raise UnsafeUrlError(detail=f"host {host!r} produced unparseable address {addr!r}") from exc
    # IPv4-mapped IPv6 (::ffff:a.b.c.d) must be unwrapped before the range
    # checks, else a mapped private v4 slips past the v6 predicates.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if _is_blocked_ip(ip):
        raise UnsafeUrlError(
            detail=f"host {host!r} resolves to blocked address {addr} (private/loopback/link-local)"
        )


def assert_url_allowed(url: str) -> list[str]:
    """Validate ``url`` for SSRF safety; return the validated IP list.

    Raises :class:`UnsafeUrlError` for a disallowed scheme, a missing
    host, an unresolvable host, or a host that resolves to (or is) a
    blocked address. The returned IP strings are the resolved set, for a
    caller that wants to pin.
    """
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError(detail=f"scheme {scheme!r} not allowed (http/https only): {url!r}")
    host = parts.hostname
    if not host:
        raise UnsafeUrlError(detail=f"URL has no host: {url!r}")

    # Host given as an IP literal — validate directly, no DNS.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        _check_addr(host, str(literal))
        return [str(literal)]

    port = parts.port or (443 if scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        # Cannot resolve → cannot prove safe → refuse (fail-closed).
        raise UnsafeUrlError(detail=f"cannot resolve host {host!r}: {exc}") from exc

    ips: list[str] = []
    for info in infos:
        addr = info[4][0]
        _check_addr(host, addr)  # raises on the first blocked address
        ips.append(addr)
    if not ips:
        raise UnsafeUrlError(detail=f"host {host!r} did not resolve to any address")
    return ips


__all__ = ["assert_url_allowed"]
