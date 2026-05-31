"""4-tier scrape ladder (slice R3 ADR-017).

Tiers:

1. **Tier-1 webfetch** (``httpx`` + BeautifulSoup-style parsing) — the
   cheapest, fastest path. Most public APIs + simple HTML scraping
   pages live here.
2. **Tier-2 Playwright** (Chromium headless) — for sites that require
   JS execution or HttpOnly cookies. Adds a ~5x latency penalty.
3. **Tier-3 Camoufox** (Firefox stealth) — for sites with
   fingerprint-based anti-bot (Cloudflare, DataDome). 10x latency.
4. **Tier-4 Camoufox + 2Captcha** — for sites that throw an explicit
   CAPTCHA challenge. Costs USD per solve; requires opt-in via
   `scrape_tier_max=4` (default 3 disables this tier).

Slice R3 ships **Tier-1 only** as a working implementation; Tier-2/3/4
raise :class:`ScrapeNotImplementedError` until the deployment-foundation
slice adds Playwright + Camoufox + 2Captcha dependencies. The ladder
shape is stable so adding a higher tier is one method swap.

Per ADR-017 escalation policy: each tier may declare an explicit
``allowed_fallbacks`` set. The ladder traverses ``[default_tier, *fallbacks]``
on :class:`ScrapeBlockedError`; any other exception propagates.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

import httpx

from iguanatrader.contexts.research.scraping.errors import (
    ScrapeBlockedError,
    ScrapeNotImplementedError,
)
from iguanatrader.contexts.research.scraping.robots_check import is_robots_allowed
from iguanatrader.contexts.research.scraping.url_guard import assert_url_allowed
from iguanatrader.contexts.research.scraping.user_agent import UserAgentRotation

#: #13: cap on redirect hops the Tier-1 fetch follows manually. Each hop is
#: re-validated against the SSRF guard + robots before the next request,
#: so a public URL cannot redirect into a private address.
_MAX_REDIRECTS = 5

logger = logging.getLogger(__name__)


class ScrapeTier(IntEnum):
    """Numeric scrape-tier identifier.

    ``IntEnum`` so the comparison ``tier <= scrape_tier_max`` is natural.
    """

    TIER_1_WEBFETCH = 1
    TIER_2_PLAYWRIGHT = 2
    TIER_3_CAMOUFOX = 3
    TIER_4_CAPTCHA = 4


@dataclass(frozen=True, slots=True)
class ScrapeResult:
    """Result of a successful tier fetch."""

    body: str
    status_code: int
    final_url: str
    tier_used: ScrapeTier


TierFn = Callable[[str, UserAgentRotation, dict[str, Any] | None], Awaitable[ScrapeResult]]


# ----------------------------------------------------------------------
# Tier implementations
# ----------------------------------------------------------------------


async def fetch_tier1(
    url: str,
    user_agents: UserAgentRotation,
    headers: dict[str, Any] | None = None,
) -> ScrapeResult:
    """Tier-1 webfetch via :mod:`httpx`. Honours robots.txt."""
    ua = user_agents.next()
    request_headers: dict[str, str] = {"User-Agent": ua}
    if headers:
        request_headers.update({k: str(v) for k, v in headers.items()})

    # #13: redirects are followed MANUALLY so every hop is re-validated by
    # the SSRF guard + robots before the next request. ``follow_redirects``
    # stays off so httpx can never silently chase a Location into a private
    # address. ``assert_url_allowed`` raises ``UnsafeUrlError`` (not a
    # ScrapeBlockedError) so the ladder does not escalate-and-retry a
    # dangerous URL.
    current_url = url
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
        for _hop in range(_MAX_REDIRECTS + 1):
            assert_url_allowed(current_url)
            if not is_robots_allowed(current_url, ua):
                raise ScrapeBlockedError(
                    detail=f"robots.txt forbids fetch of {current_url} for UA {ua!r}"
                )
            response = await client.get(current_url, headers=request_headers)
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    break
                # Resolve relative redirects against the current URL.
                current_url = str(response.url.join(location))
                continue
            break
        else:
            raise ScrapeBlockedError(detail=f"tier-1 exceeded {_MAX_REDIRECTS} redirects for {url}")

    if response.status_code in {403, 429, 503}:
        raise ScrapeBlockedError(
            detail=f"tier-1 blocked at {current_url} (status={response.status_code})"
        )
    response.raise_for_status()
    return ScrapeResult(
        body=response.text,
        status_code=response.status_code,
        final_url=str(response.url),
        tier_used=ScrapeTier.TIER_1_WEBFETCH,
    )


async def fetch_tier2_stub(
    url: str,
    user_agents: UserAgentRotation,
    headers: dict[str, Any] | None = None,
) -> ScrapeResult:
    """Placeholder for Tier-2 Playwright (slice R3 deferred to deployment slice)."""
    raise ScrapeNotImplementedError(
        detail="tier-2 Playwright not installed; deployment-foundation slice wires it"
    )


async def fetch_tier3_stub(
    url: str,
    user_agents: UserAgentRotation,
    headers: dict[str, Any] | None = None,
) -> ScrapeResult:
    """Placeholder for Tier-3 Camoufox (slice R3 deferred)."""
    raise ScrapeNotImplementedError(
        detail="tier-3 Camoufox not installed; deployment-foundation slice wires it"
    )


async def fetch_tier4_stub(
    url: str,
    user_agents: UserAgentRotation,
    headers: dict[str, Any] | None = None,
) -> ScrapeResult:
    """Placeholder for Tier-4 Camoufox + 2Captcha (slice R3 deferred)."""
    raise ScrapeNotImplementedError(
        detail="tier-4 CAPTCHA solver not installed; deployment-foundation slice wires it"
    )


# ----------------------------------------------------------------------
# Ladder orchestrator
# ----------------------------------------------------------------------


_DEFAULT_TIER_FNS: dict[ScrapeTier, TierFn] = {
    ScrapeTier.TIER_1_WEBFETCH: fetch_tier1,
    ScrapeTier.TIER_2_PLAYWRIGHT: fetch_tier2_stub,
    ScrapeTier.TIER_3_CAMOUFOX: fetch_tier3_stub,
    ScrapeTier.TIER_4_CAPTCHA: fetch_tier4_stub,
}


@dataclass
class ScrapeLadder:
    """Wraps tier callables with escalation policy.

    Construction is dependency-injection style — tests pass fakes for
    each tier; production composes the canonical implementations.
    """

    user_agents: UserAgentRotation
    tier_max: ScrapeTier = ScrapeTier.TIER_3_CAMOUFOX
    tier_fns: dict[ScrapeTier, TierFn] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.tier_fns is None:
            self.tier_fns = dict(_DEFAULT_TIER_FNS)

    async def fetch(
        self,
        url: str,
        *,
        start_tier: ScrapeTier = ScrapeTier.TIER_1_WEBFETCH,
        headers: dict[str, Any] | None = None,
    ) -> ScrapeResult:
        """Try ``start_tier``; on :class:`ScrapeBlockedError` escalate up
        to ``tier_max``."""
        last_exc: Exception | None = None
        tier_value = int(start_tier)
        max_value = int(self.tier_max)
        while tier_value <= max_value:
            tier = ScrapeTier(tier_value)
            fn = self.tier_fns[tier]
            try:
                return await fn(url, self.user_agents, headers)
            except ScrapeBlockedError as exc:
                last_exc = exc
                logger.info(
                    "research.scraping.tier_escalation",
                    extra={"url": url, "from_tier": int(tier), "reason": str(exc)},
                )
                tier_value += 1
                continue
        raise ScrapeBlockedError(
            detail=(
                f"all tiers up to {self.tier_max} blocked for {url}; " f"last error: {last_exc}"
            ),
        )


__all__ = [
    "ScrapeLadder",
    "ScrapeResult",
    "ScrapeTier",
    "TierFn",
    "fetch_tier1",
    "fetch_tier2_stub",
    "fetch_tier3_stub",
    "fetch_tier4_stub",
]
