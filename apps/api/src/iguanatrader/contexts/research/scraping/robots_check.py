"""robots.txt compliance checker (slice R3 FR79).

Validates a target URL against the site's ``robots.txt`` directives via
:class:`urllib.robotparser.RobotFileParser`. 24h cache keyed by host
+ User-Agent so repeated scrapes don't hit the robots endpoint on
every request.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Final
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

logger = logging.getLogger(__name__)

#: Cache TTL — robots.txt rarely changes.
_CACHE_TTL_SECONDS: Final[float] = 24 * 60 * 60.0

# In-process cache: (host, user_agent) → (parser, expires_at).
_cache: dict[tuple[str, str], tuple[RobotFileParser, float]] = {}
_cache_lock = threading.Lock()


def _get_parser(host: str, user_agent: str) -> RobotFileParser:
    """Return a cached :class:`RobotFileParser` for ``host``."""
    key = (host, user_agent)
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None and cached[1] > time.monotonic():
            return cached[0]
    parser = RobotFileParser()
    parser.set_url(f"https://{host}/robots.txt")
    try:
        parser.read()
    except Exception:
        logger.warning(
            "research.scraping.robots_unreachable",
            extra={"host": host},
        )
    with _cache_lock:
        _cache[key] = (parser, time.monotonic() + _CACHE_TTL_SECONDS)
    return parser


def is_robots_allowed(url: str, user_agent: str) -> bool:
    """Return True iff ``user_agent`` may fetch ``url`` per the host's robots.txt.

    Failure to fetch / parse robots.txt defaults to **allowed** (so the
    scraper isn't blocked by a 5xx on the robots endpoint), but logs a
    structlog warning. Operators paranoid about strict compliance can
    flip the default in a future config-knob slice.
    """
    parts = urlsplit(url)
    host = parts.netloc.lower()
    if not host:
        return True
    parser = _get_parser(host, user_agent)
    return parser.can_fetch(user_agent, url)


def reset_cache_for_tests() -> None:
    """Wipe the in-process robots cache. Test-only."""
    with _cache_lock:
        _cache.clear()


__all__ = ["is_robots_allowed", "reset_cache_for_tests"]
