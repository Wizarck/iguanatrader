"""Unit tests for :class:`HindsightRetainHandler` (slice R6).

Mocks :class:`ResearchRepository` and uses :class:`InMemoryHindsightAdapter`
to verify the bus-bridge handler:

* On ``ResearchBriefSynthesized`` event -> ``retain`` invoked once with
  the brief thesis as content.
* If repository lookup fails -> log + swallow (FR80 graceful).
* If hindsight raises -> log + swallow.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from iguanatrader.contexts.research.events import ResearchBriefSynthesized
from iguanatrader.contexts.research.hindsight import HindsightUnavailable
from iguanatrader.contexts.research.hindsight.in_memory import (
    InMemoryHindsightAdapter,
)
from iguanatrader.contexts.research.hindsight.retain_handler import (
    HindsightRetainHandler,
)


def _make_event() -> ResearchBriefSynthesized:
    return ResearchBriefSynthesized(
        tenant_id=uuid4(),
        brief_id=uuid4(),
        symbol_universe_id=uuid4(),
        version=3,
        methodology="three_pillar",
    )


def _make_brief_row(thesis: str = "AAPL Q4 strong earnings") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        thesis_text=thesis,
        version=3,
        methodology="three_pillar",
        created_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_event_triggers_retain_with_thesis() -> None:
    event = _make_event()
    brief = _make_brief_row()
    repo = AsyncMock()
    repo.get_brief_by_id = AsyncMock(return_value=brief)
    hindsight = InMemoryHindsightAdapter()
    handler = HindsightRetainHandler(hindsight=hindsight, repository=repo)

    await handler._on_brief_synthesized(event)

    bank = f"iguanatrader-research-{event.tenant_id}"
    entries = hindsight._entries(bank)
    assert len(entries) == 1
    assert "AAPL" in entries[0]
    repo.get_brief_by_id.assert_awaited_once_with(event.brief_id)


@pytest.mark.asyncio
async def test_repository_failure_swallowed() -> None:
    event = _make_event()
    repo = AsyncMock()
    repo.get_brief_by_id = AsyncMock(side_effect=RuntimeError("DB down"))
    hindsight = InMemoryHindsightAdapter()
    handler = HindsightRetainHandler(hindsight=hindsight, repository=repo)

    # MUST NOT raise.
    await handler._on_brief_synthesized(event)

    bank = f"iguanatrader-research-{event.tenant_id}"
    assert hindsight._entries(bank) == []


@pytest.mark.asyncio
async def test_hindsight_unavailable_swallowed() -> None:
    event = _make_event()
    brief = _make_brief_row()
    repo = AsyncMock()
    repo.get_brief_by_id = AsyncMock(return_value=brief)
    hindsight = AsyncMock()
    hindsight.retain = AsyncMock(
        side_effect=HindsightUnavailable(detail="server unreachable"),
    )
    handler = HindsightRetainHandler(hindsight=hindsight, repository=repo)

    # MUST NOT raise.
    await handler._on_brief_synthesized(event)

    hindsight.retain.assert_awaited_once()


@pytest.mark.asyncio
async def test_brief_not_found_swallowed() -> None:
    event = _make_event()
    repo = AsyncMock()
    repo.get_brief_by_id = AsyncMock(return_value=None)
    hindsight = InMemoryHindsightAdapter()
    handler = HindsightRetainHandler(hindsight=hindsight, repository=repo)

    await handler._on_brief_synthesized(event)
    assert hindsight._entries(f"iguanatrader-research-{event.tenant_id}") == []
