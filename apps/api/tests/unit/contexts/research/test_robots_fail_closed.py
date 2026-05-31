"""#14: robots.txt checker fail-closed + empty-host behaviour."""

from __future__ import annotations

import pytest
from iguanatrader.contexts.research.scraping import robots_check
from iguanatrader.contexts.research.scraping.robots_check import (
    is_robots_allowed,
    reset_cache_for_tests,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    reset_cache_for_tests()


def test_empty_host_is_rejected() -> None:
    # A URL with no host cannot be robots-validated → deny (was: allow).
    assert is_robots_allowed("not-a-url", "ua") is False


def test_indeterminate_denies_when_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force an indeterminate fetch (timeout / 5xx) and fail-closed policy.
    monkeypatch.setattr(robots_check, "_fetch_robots", lambda *a, **k: False)
    monkeypatch.setenv("SCRAPE_ROBOTS_FAIL_CLOSED", "true")
    assert is_robots_allowed("https://example.com/x", "ua") is False


def test_indeterminate_allows_when_fail_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(robots_check, "_fetch_robots", lambda *a, **k: False)
    monkeypatch.setenv("SCRAPE_ROBOTS_FAIL_CLOSED", "false")
    assert is_robots_allowed("https://example.com/x", "ua") is True


def test_definitive_allow_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    # A successful fetch with an allow-all body permits the URL even under
    # a fail-closed policy (the answer is definitive, not indeterminate).
    def _fetch(parser, host, ua):  # noqa: ANN001
        parser.parse(["User-agent: *", "Allow: /"])
        return True

    monkeypatch.setattr(robots_check, "_fetch_robots", _fetch)
    monkeypatch.setenv("SCRAPE_ROBOTS_FAIL_CLOSED", "true")
    assert is_robots_allowed("https://example.com/x", "ua") is True


def test_definitive_disallow_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fetch(parser, host, ua):  # noqa: ANN001
        parser.parse(["User-agent: *", "Disallow: /"])
        return True

    monkeypatch.setattr(robots_check, "_fetch_robots", _fetch)
    monkeypatch.setenv("SCRAPE_ROBOTS_FAIL_CLOSED", "false")
    assert is_robots_allowed("https://example.com/secret", "ua") is False
