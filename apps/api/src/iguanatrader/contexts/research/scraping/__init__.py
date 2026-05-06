"""4-tier scrape ladder + politeness primitives (slice R3 ADR-017).

Public exports:

* :class:`ScrapeTier` — enum of the 4 tiers.
* :class:`ScrapeBlockedError` — raised when a tier hits a block; the
  ladder catches it + escalates to the next tier.
* :class:`ScrapeLadder` — wraps the 4 tier callables with policy.
* :func:`fetch_tier1` — Tier-1 (httpx + simple parsing) implementation.
* :func:`fetch_tier2_stub` / :func:`fetch_tier3_stub` /
  :func:`fetch_tier4_stub` — placeholders raising :class:`NotImplementedError`
  until a deployment slice adds Playwright + Camoufox dependencies.
* :class:`UserAgentRotation` + :func:`is_robots_allowed` — politeness
  helpers per FR79.
"""

from __future__ import annotations

from iguanatrader.contexts.research.scraping.errors import ScrapeBlockedError
from iguanatrader.contexts.research.scraping.ladder import (
    ScrapeLadder,
    ScrapeTier,
    fetch_tier1,
    fetch_tier2_stub,
    fetch_tier3_stub,
    fetch_tier4_stub,
)
from iguanatrader.contexts.research.scraping.robots_check import is_robots_allowed
from iguanatrader.contexts.research.scraping.user_agent import UserAgentRotation

__all__ = [
    "ScrapeBlockedError",
    "ScrapeLadder",
    "ScrapeTier",
    "UserAgentRotation",
    "fetch_tier1",
    "fetch_tier2_stub",
    "fetch_tier3_stub",
    "fetch_tier4_stub",
    "is_robots_allowed",
]
