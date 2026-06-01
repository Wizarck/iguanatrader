"""robots.txt compliance checker (slice R3 FR79; hardened in #14).

Validates a target URL against the site's ``robots.txt`` directives via
:class:`urllib.robotparser.RobotFileParser`. Cached per host + User-Agent
so repeated scrapes don't hit the robots endpoint on every request.

#14 hardening over the original:

* **Bounded fetch** — ``RobotFileParser.read()`` issues an un-timed
  ``urlopen`` that can hang the worker indefinitely. We fetch robots.txt
  ourselves with a timeout and feed the body to the parser, preserving
  the standard status semantics (404 ⇒ allow-all, 401/403 ⇒ disallow-all).
* **Fail-closed in production** — an *indeterminate* result (timeout /
  5xx / network error) no longer blanket-allows. In production-like envs
  (or when ``SCRAPE_ROBOTS_FAIL_CLOSED`` is truthy) it denies; in
  dev/test it allows. The previous always-allow-on-error let a flaky
  robots endpoint silently disable compliance.
* **Short failure TTL** — a failed fetch is cached for seconds, not 24h,
  so a transient outage doesn't pin "indeterminate" for a day.
* **Empty host is rejected** (cannot validate ⇒ do not fetch).
* **Crawl-delay exposed** via :func:`robots_crawl_delay` for the caller's
  rate limiter.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Final
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

logger = logging.getLogger(__name__)

#: Cache TTL for a SUCCESSFUL fetch — robots.txt rarely changes.
_CACHE_TTL_SECONDS: Final[float] = 24 * 60 * 60.0
#: Cache TTL for a FAILED/indeterminate fetch — retry soon, don't pin a
#: day-long "unknown" on a transient blip.
_FAILURE_TTL_SECONDS: Final[float] = 60.0
#: Hard timeout on the robots.txt fetch.
_ROBOTS_TIMEOUT_SECONDS: Final[float] = 5.0

# In-process cache: (host, user_agent) → (parser, expires_at, fetch_ok).
_cache: dict[tuple[str, str], tuple[RobotFileParser, float, bool]] = {}
_cache_lock = threading.Lock()

_TRUTHY: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})


def _fail_closed_default() -> bool:
    """Whether an indeterminate robots result should DENY.

    Explicit ``SCRAPE_ROBOTS_FAIL_CLOSED`` wins; otherwise default to
    closed in production-like envs (paper/live/production) and open in
    dev/test. Reuses the shared production-like classifier so the policy
    matches the cookie-security guard (#10).
    """
    raw = os.environ.get("SCRAPE_ROBOTS_FAIL_CLOSED")
    if raw is not None:
        return raw.strip().lower() in _TRUTHY
    from iguanatrader.config.settings import is_production_like

    return is_production_like(os.environ.get("IGUANATRADER_ENV", "dev"))


def _fetch_robots(parser: RobotFileParser, host: str, user_agent: str) -> bool:
    """Populate ``parser`` from ``host``'s robots.txt. Return True iff the
    answer is DEFINITIVE (a real body, or a status with defined semantics).

    Mirrors ``RobotFileParser.read``'s status handling but adds a timeout:
    404/4xx (except 401/403) ⇒ allow-all; 401/403 ⇒ disallow-all; 2xx ⇒
    parse the body. 5xx / timeout / network error ⇒ indeterminate (False).
    """
    robots_url = f"https://{host}/robots.txt"
    req = urllib.request.Request(robots_url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=_ROBOTS_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        parser.parse(raw.splitlines())
        return True
    except urllib.error.HTTPError as err:
        if err.code in (401, 403):
            parser.disallow_all = True  # type: ignore[attr-defined]
            return True
        if 400 <= err.code < 500:
            parser.allow_all = True  # type: ignore[attr-defined]
            return True
        # 5xx — indeterminate.
        logger.warning(
            "research.scraping.robots_server_error", extra={"host": host, "status": err.code}
        )
        return False
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning(
            "research.scraping.robots_unreachable", extra={"host": host, "error": str(exc)}
        )
        return False


def _get_entry(host: str, user_agent: str) -> tuple[RobotFileParser, bool]:
    """Return the cached ``(parser, fetch_ok)`` for ``host``, fetching if stale."""
    key = (host, user_agent)
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None and cached[1] > time.monotonic():
            return cached[0], cached[2]
    parser = RobotFileParser()
    parser.set_url(f"https://{host}/robots.txt")
    fetch_ok = _fetch_robots(parser, host, user_agent)
    ttl = _CACHE_TTL_SECONDS if fetch_ok else _FAILURE_TTL_SECONDS
    with _cache_lock:
        _cache[key] = (parser, time.monotonic() + ttl, fetch_ok)
    return parser, fetch_ok


def is_robots_allowed(url: str, user_agent: str) -> bool:
    """Return True iff ``user_agent`` may fetch ``url`` per the host's robots.txt.

    A DEFINITIVE robots answer is honoured exactly. An INDETERMINATE
    result (timeout / 5xx / network error) is resolved by
    :func:`_fail_closed_default`: deny in production-like envs, allow in
    dev/test. An empty host is rejected (cannot validate ⇒ deny).
    """
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if not host:
        # #14: previously returned True (allowed). A URL we cannot attribute
        # to a host cannot be robots-validated — refuse it.
        logger.warning("research.scraping.robots_empty_host", extra={"url": url})
        return False
    parser, fetch_ok = _get_entry(host, user_agent)
    if not fetch_ok:
        allowed = not _fail_closed_default()
        logger.warning(
            "research.scraping.robots_indeterminate",
            extra={"host": host, "fail_closed": not allowed, "allowed": allowed},
        )
        return allowed
    return parser.can_fetch(user_agent, url)


def robots_crawl_delay(url: str, user_agent: str) -> float | None:
    """Return the host's ``Crawl-delay`` for ``user_agent`` in seconds, or None.

    #14: exposed so the caller's rate limiter can honour the directive.
    Returns None when robots could not be fetched or sets no delay.
    """
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if not host:
        return None
    parser, fetch_ok = _get_entry(host, user_agent)
    if not fetch_ok:
        return None
    delay = parser.crawl_delay(user_agent)
    return float(delay) if delay is not None else None


def reset_cache_for_tests() -> None:
    """Wipe the in-process robots cache. Test-only."""
    with _cache_lock:
        _cache.clear()


__all__ = ["is_robots_allowed", "robots_crawl_delay", "reset_cache_for_tests"]
