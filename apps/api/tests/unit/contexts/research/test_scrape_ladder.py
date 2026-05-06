"""Unit tests for the 4-tier scrape ladder (slice R3 ADR-017)."""

from __future__ import annotations

from typing import Any

import pytest
from iguanatrader.contexts.research.scraping import (
    ScrapeBlockedError,
    ScrapeLadder,
    ScrapeTier,
    UserAgentRotation,
)
from iguanatrader.contexts.research.scraping.errors import ScrapeNotImplementedError
from iguanatrader.contexts.research.scraping.ladder import (
    ScrapeResult,
    fetch_tier2_stub,
    fetch_tier3_stub,
    fetch_tier4_stub,
)


@pytest.fixture
def user_agents() -> UserAgentRotation:
    return UserAgentRotation()


@pytest.mark.asyncio
async def test_tier1_blocked_escalates_to_tier2(user_agents: UserAgentRotation) -> None:
    async def tier1_blocked(
        url: str, ua: UserAgentRotation, headers: dict[str, Any] | None
    ) -> ScrapeResult:
        raise ScrapeBlockedError(detail="tier-1 fake block")

    async def tier2_ok(
        url: str, ua: UserAgentRotation, headers: dict[str, Any] | None
    ) -> ScrapeResult:
        return ScrapeResult(
            body="<html>ok</html>",
            status_code=200,
            final_url=url,
            tier_used=ScrapeTier.TIER_2_PLAYWRIGHT,
        )

    ladder = ScrapeLadder(
        user_agents=user_agents,
        tier_max=ScrapeTier.TIER_3_CAMOUFOX,
        tier_fns={
            ScrapeTier.TIER_1_WEBFETCH: tier1_blocked,
            ScrapeTier.TIER_2_PLAYWRIGHT: tier2_ok,
            ScrapeTier.TIER_3_CAMOUFOX: fetch_tier3_stub,
            ScrapeTier.TIER_4_CAPTCHA: fetch_tier4_stub,
        },
    )
    result = await ladder.fetch("https://example.test/")
    assert result.tier_used == ScrapeTier.TIER_2_PLAYWRIGHT
    assert result.status_code == 200


@pytest.mark.asyncio
async def test_all_tiers_blocked_raises_final(user_agents: UserAgentRotation) -> None:
    async def always_blocked(
        url: str, ua: UserAgentRotation, headers: dict[str, Any] | None
    ) -> ScrapeResult:
        raise ScrapeBlockedError(detail="blocked")

    ladder = ScrapeLadder(
        user_agents=user_agents,
        tier_max=ScrapeTier.TIER_2_PLAYWRIGHT,
        tier_fns={
            ScrapeTier.TIER_1_WEBFETCH: always_blocked,
            ScrapeTier.TIER_2_PLAYWRIGHT: always_blocked,
            ScrapeTier.TIER_3_CAMOUFOX: fetch_tier3_stub,
            ScrapeTier.TIER_4_CAPTCHA: fetch_tier4_stub,
        },
    )
    with pytest.raises(ScrapeBlockedError):
        await ladder.fetch("https://example.test/")


@pytest.mark.asyncio
async def test_tier_max_3_does_not_attempt_tier4(user_agents: UserAgentRotation) -> None:
    """tier_max=3 means we never attempt tier-4 even when tier-3 blocks."""

    async def always_blocked(
        url: str, ua: UserAgentRotation, headers: dict[str, Any] | None
    ) -> ScrapeResult:
        raise ScrapeBlockedError(detail="blocked")

    tier4_called = False

    async def tier4_tracker(
        url: str, ua: UserAgentRotation, headers: dict[str, Any] | None
    ) -> ScrapeResult:
        nonlocal tier4_called
        tier4_called = True
        raise AssertionError("tier-4 must not be reached when tier_max=3")

    ladder = ScrapeLadder(
        user_agents=user_agents,
        tier_max=ScrapeTier.TIER_3_CAMOUFOX,
        tier_fns={
            ScrapeTier.TIER_1_WEBFETCH: always_blocked,
            ScrapeTier.TIER_2_PLAYWRIGHT: always_blocked,
            ScrapeTier.TIER_3_CAMOUFOX: always_blocked,
            ScrapeTier.TIER_4_CAPTCHA: tier4_tracker,
        },
    )
    with pytest.raises(ScrapeBlockedError):
        await ladder.fetch("https://example.test/")
    assert tier4_called is False


@pytest.mark.asyncio
async def test_tier2_stub_raises_not_implemented(user_agents: UserAgentRotation) -> None:
    with pytest.raises(ScrapeNotImplementedError):
        await fetch_tier2_stub("https://example.test/", user_agents, None)


@pytest.mark.asyncio
async def test_tier3_stub_raises_not_implemented(user_agents: UserAgentRotation) -> None:
    with pytest.raises(ScrapeNotImplementedError):
        await fetch_tier3_stub("https://example.test/", user_agents, None)


@pytest.mark.asyncio
async def test_user_agent_rotation_includes_ops_email(user_agents: UserAgentRotation) -> None:
    for _ in range(5):
        ua = user_agents.next()
        assert "+arturo6ramirez@gmail.com" in ua


def test_user_agent_rotation_round_robin() -> None:
    rotation = UserAgentRotation()
    seen = [rotation.next() for _ in range(10)]
    # 3-entry pool → first and 4th identical.
    assert seen[0] == seen[3]
    assert seen[1] == seen[4]
