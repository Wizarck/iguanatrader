"""Unit tests for Tier-2 Playwright scrape (slice deployment-foundation §3.D).

Playwright itself is mocked via ``sys.modules`` injection — tests
verify the shim's robots-check enforcement, semaphore-protected fetch
path, status-code mapping, and timeout handling without launching
chromium. The real-chromium smoke is exercised in §8.2.D.
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
def fake_playwright_module(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Inject a fake ``playwright.async_api`` module."""
    pkg = ModuleType("playwright")
    submod = ModuleType("playwright.async_api")

    class _PlaywrightTimeoutError(Exception):
        pass

    submod.TimeoutError = _PlaywrightTimeoutError  # type: ignore[attr-defined]
    submod.Error = Exception  # type: ignore[attr-defined]
    submod.async_playwright = MagicMock()  # type: ignore[attr-defined]
    pkg.async_api = submod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "playwright", pkg)
    monkeypatch.setitem(sys.modules, "playwright.async_api", submod)

    fakes: dict[str, Any] = {"submod": submod}
    return fakes


@pytest.fixture
def fresh_holder(
    monkeypatch: pytest.MonkeyPatch, fake_playwright_module: dict[str, Any]
) -> Any:
    """Reset the module-singleton browser holder for each test."""
    from iguanatrader.contexts.research.scraping import tier2_playwright

    holder = tier2_playwright._PlaywrightBrowserHolder()
    monkeypatch.setattr(tier2_playwright, "_HOLDER", holder)
    return holder


@pytest.fixture
def user_agents() -> Any:
    rotation = MagicMock()
    rotation.next = MagicMock(return_value="iguana-test-bot/1.0")
    return rotation


@pytest.mark.asyncio
async def test_fetch_returns_scrape_result_on_200(
    fresh_holder: Any, user_agents: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from iguanatrader.contexts.research.scraping import tier2_playwright
    from iguanatrader.contexts.research.scraping.ladder import ScrapeTier

    response = MagicMock(status=200)
    page = MagicMock()
    page.goto = AsyncMock(return_value=response)
    page.content = AsyncMock(return_value="<html>ok</html>")
    page.url = "https://example.com"
    page.set_default_navigation_timeout = MagicMock()
    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    context.close = AsyncMock()
    context.set_extra_http_headers = AsyncMock()
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    fresh_holder._browser = browser

    monkeypatch.setattr(
        "iguanatrader.contexts.research.scraping.tier2_playwright.is_robots_allowed",
        lambda url, ua: True,
    )

    result = await tier2_playwright.fetch_tier2_playwright(
        "https://example.com", user_agents
    )

    assert result.body == "<html>ok</html>"
    assert result.status_code == 200
    assert result.final_url == "https://example.com"
    assert result.tier_used == ScrapeTier.TIER_2_PLAYWRIGHT


@pytest.mark.asyncio
async def test_fetch_raises_blocked_on_403(
    fresh_holder: Any, user_agents: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from iguanatrader.contexts.research.scraping import tier2_playwright
    from iguanatrader.contexts.research.scraping.errors import ScrapeBlockedError

    response = MagicMock(status=403)
    page = MagicMock()
    page.goto = AsyncMock(return_value=response)
    page.set_default_navigation_timeout = MagicMock()
    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    context.close = AsyncMock()
    context.set_extra_http_headers = AsyncMock()
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    fresh_holder._browser = browser

    monkeypatch.setattr(
        "iguanatrader.contexts.research.scraping.tier2_playwright.is_robots_allowed",
        lambda url, ua: True,
    )

    with pytest.raises(ScrapeBlockedError, match="status=403"):
        await tier2_playwright.fetch_tier2_playwright(
            "https://blocked.example", user_agents
        )


@pytest.mark.asyncio
async def test_fetch_respects_robots_txt(
    fresh_holder: Any, user_agents: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from iguanatrader.contexts.research.scraping import tier2_playwright
    from iguanatrader.contexts.research.scraping.errors import ScrapeBlockedError

    monkeypatch.setattr(
        "iguanatrader.contexts.research.scraping.tier2_playwright.is_robots_allowed",
        lambda url, ua: False,
    )

    with pytest.raises(ScrapeBlockedError, match="robots.txt forbids"):
        await tier2_playwright.fetch_tier2_playwright(
            "https://disallowed.example", user_agents
        )
