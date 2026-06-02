"""#13: SSRF guard for the scrape ladder."""

from __future__ import annotations

import socket
from collections.abc import Callable
from typing import Any

import pytest
from iguanatrader.contexts.research.scraping import url_guard
from iguanatrader.contexts.research.scraping.errors import UnsafeUrlError
from iguanatrader.contexts.research.scraping.url_guard import assert_url_allowed


def _fake_getaddrinfo(ip: str) -> Callable[..., list[Any]]:
    def _inner(host: object, port: object, *args: object, **kwargs: object) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port))]

    return _inner


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/x",  # disallowed scheme
        "file:///etc/passwd",  # disallowed scheme
        "https://",  # no host
        "http://127.0.0.1/",  # loopback literal
        "http://10.0.0.5/",  # RFC1918 private literal
        "http://169.254.169.254/latest/meta-data/",  # cloud-metadata link-local
        "http://[::1]/",  # IPv6 loopback literal
        "http://0.0.0.0/",  # unspecified
    ],
)
def test_rejects_dangerous_urls(url: str) -> None:
    with pytest.raises(UnsafeUrlError):
        assert_url_allowed(url)


def test_allows_public_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(url_guard.socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))  # type: ignore[attr-defined]
    ips = assert_url_allowed("https://example.com/path")
    assert ips == ["93.184.216.34"]


def test_rejects_public_host_resolving_to_private(monkeypatch: pytest.MonkeyPatch) -> None:
    # The SSRF pivot: a benign-looking hostname whose DNS answer is a
    # private address (also models a redirect target re-validated per hop).
    monkeypatch.setattr(url_guard.socket, "getaddrinfo", _fake_getaddrinfo("192.168.1.10"))  # type: ignore[attr-defined]
    with pytest.raises(UnsafeUrlError):
        assert_url_allowed("https://rebind.evil.test/")


def test_rejects_unresolvable_host(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: object, **kwargs: object) -> list[Any]:
        raise socket.gaierror("name resolution failed")

    monkeypatch.setattr(url_guard.socket, "getaddrinfo", _boom)  # type: ignore[attr-defined]
    with pytest.raises(UnsafeUrlError):
        assert_url_allowed("https://nonexistent.invalid/")


def test_rejects_ipv4_mapped_private_v6(monkeypatch: pytest.MonkeyPatch) -> None:
    # ::ffff:10.0.0.1 must be unwrapped before the range check.
    monkeypatch.setattr(url_guard.socket, "getaddrinfo", _fake_getaddrinfo("::ffff:10.0.0.1"))  # type: ignore[attr-defined]
    with pytest.raises(UnsafeUrlError):
        assert_url_allowed("https://mapped.test/")
