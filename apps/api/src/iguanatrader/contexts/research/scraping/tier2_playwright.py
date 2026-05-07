"""Production Tier-2 scrape implementation — Chromium via Playwright.

Replaces :func:`fetch_tier2_stub` from slice R3's ladder. The composition
root swaps the entry in ``_DEFAULT_TIER_FNS`` (or constructs
:class:`ScrapeLadder` with `tier_fns=...`).

Browser lifecycle: a single :class:`Browser` per process; pages are
created per fetch and closed immediately. Concurrency is gated by the
asyncio loop's natural cooperation — no explicit semaphore needed at
the volumes this slice anticipates (≤5 concurrent ladder escalations).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from iguanatrader.contexts.research.scraping.errors import (
    ScrapeBlockedError,
    ScrapeNotImplementedError,
)
from iguanatrader.contexts.research.scraping.ladder import ScrapeResult, ScrapeTier
from iguanatrader.contexts.research.scraping.robots_check import is_robots_allowed
from iguanatrader.contexts.research.scraping.user_agent import UserAgentRotation

logger = logging.getLogger(__name__)


_NAVIGATION_TIMEOUT_MS = 30_000
_TOTAL_TIMEOUT_S = 60.0
_MAX_CONCURRENT_PAGES = 5


class _PlaywrightBrowserHolder:
    """Process-singleton wrapper around the Chromium browser handle."""

    def __init__(self) -> None:
        self._browser: Any = None
        self._playwright: Any = None
        self._semaphore = asyncio.Semaphore(_MAX_CONCURRENT_PAGES)
        self._lock = asyncio.Lock()

    async def _ensure(self) -> Any:
        if self._browser is not None:
            return self._browser
        async with self._lock:
            if self._browser is not None:
                return self._browser
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                raise ScrapeNotImplementedError(
                    detail=(
                        "playwright is not installed. Run "
                        "`poetry install && poetry run playwright install chromium` "
                        "before invoking Tier-2 scrape."
                    ),
                ) from exc
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
            return self._browser

    async def fetch(
        self,
        url: str,
        user_agent: str,
        extra_headers: dict[str, str] | None,
    ) -> ScrapeResult:
        async with self._semaphore:
            browser = await self._ensure()
            context = await browser.new_context(user_agent=user_agent)
            try:
                if extra_headers:
                    await context.set_extra_http_headers(extra_headers)
                page = await context.new_page()
                page.set_default_navigation_timeout(_NAVIGATION_TIMEOUT_MS)
                try:
                    response = await asyncio.wait_for(
                        page.goto(url, wait_until="domcontentloaded"),
                        timeout=_TOTAL_TIMEOUT_S,
                    )
                except (TimeoutError, asyncio.TimeoutError) as exc:
                    raise ScrapeBlockedError(
                        detail=f"tier-2 navigation timeout ({url})"
                    ) from exc
                if response is None:
                    raise ScrapeBlockedError(detail=f"tier-2 no response from {url}")
                status_code = response.status
                if status_code in {403, 429, 503}:
                    raise ScrapeBlockedError(
                        detail=f"tier-2 blocked at {url} (status={status_code})"
                    )
                body = await page.content()
                final_url = page.url
                return ScrapeResult(
                    body=body,
                    status_code=status_code,
                    final_url=final_url,
                    tier_used=ScrapeTier.TIER_2_PLAYWRIGHT,
                )
            finally:
                await context.close()

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None


_HOLDER = _PlaywrightBrowserHolder()


async def fetch_tier2_playwright(
    url: str,
    user_agents: UserAgentRotation,
    headers: dict[str, Any] | None = None,
) -> ScrapeResult:
    """Tier-2 scrape — chromium via Playwright. Honours robots.txt.

    Drop-in replacement for :func:`fetch_tier2_stub`. The composition
    root rebinds the ladder's tier dict to point Tier-2 here once the
    deployment-foundation slice's deps are installed.
    """
    ua = user_agents.next()
    if not is_robots_allowed(url, ua):
        raise ScrapeBlockedError(detail=f"robots.txt forbids fetch of {url} for UA {ua!r}")

    extra_headers: dict[str, str] | None = None
    if headers:
        extra_headers = {k: str(v) for k, v in headers.items()}

    return await _HOLDER.fetch(url, ua, extra_headers)


async def shutdown_playwright() -> None:
    """Close the process-singleton browser. Called from FastAPI lifespan teardown."""
    await _HOLDER.close()


__all__ = ["fetch_tier2_playwright", "shutdown_playwright"]
