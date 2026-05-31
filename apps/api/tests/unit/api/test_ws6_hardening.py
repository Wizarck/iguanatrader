"""WS6 hardening: #17 (XFF-aware rate-limit key) + #18 (multi-worker guard)."""

from __future__ import annotations

import pytest
from starlette.requests import Request


def _request(headers: dict[str, str], client_ip: str = "203.0.113.9") -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/auth/login",
        "scheme": "http",
        "server": ("test", 80),
        "query_string": b"",
        "client": (client_ip, 5555),
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    return Request(scope)


def test_client_ip_ignores_xff_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from iguanatrader.api.limiting import _client_ip

    monkeypatch.delenv("IGUANATRADER_TRUSTED_PROXY_HOPS", raising=False)
    req = _request({"x-forwarded-for": "1.1.1.1, 2.2.2.2"}, client_ip="203.0.113.9")
    # No trusted proxy configured → a spoofable XFF is ignored; socket IP wins.
    assert _client_ip(req) == "203.0.113.9"


def test_client_ip_uses_xff_with_one_trusted_hop(monkeypatch: pytest.MonkeyPatch) -> None:
    from iguanatrader.api.limiting import _client_ip

    monkeypatch.setenv("IGUANATRADER_TRUSTED_PROXY_HOPS", "1")
    # One trusted proxy appended the real client's IP on the RIGHT; an
    # attacker prepended a spoofed "9.9.9.9" on the left. With 1 trusted
    # hop we take the address 1 from the right → the real client, and the
    # spoofed left entry is ignored.
    req = _request({"x-forwarded-for": "9.9.9.9, 198.51.100.7"}, client_ip="10.0.0.1")
    assert _client_ip(req) == "198.51.100.7"


def test_multiworker_guard_rejects_web_concurrency_gt_1(monkeypatch: pytest.MonkeyPatch) -> None:
    from iguanatrader.api.app import _assert_single_worker_or_opted_in

    monkeypatch.delenv("IGUANATRADER_ALLOW_MULTIWORKER", raising=False)
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    with pytest.raises(RuntimeError, match="worker"):
        _assert_single_worker_or_opted_in()


def test_multiworker_guard_allows_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    from iguanatrader.api.app import _assert_single_worker_or_opted_in

    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    monkeypatch.setenv("IGUANATRADER_ALLOW_MULTIWORKER", "true")
    _assert_single_worker_or_opted_in()  # must not raise


def test_multiworker_guard_allows_single_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    from iguanatrader.api.app import _assert_single_worker_or_opted_in

    monkeypatch.delenv("IGUANATRADER_ALLOW_MULTIWORKER", raising=False)
    monkeypatch.setenv("WEB_CONCURRENCY", "1")
    _assert_single_worker_or_opted_in()  # must not raise
