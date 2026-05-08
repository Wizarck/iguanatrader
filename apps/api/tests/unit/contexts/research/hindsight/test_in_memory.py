"""Unit tests for :class:`InMemoryHindsightAdapter` (slice R6)."""

from __future__ import annotations

import pytest
from iguanatrader.contexts.research.hindsight.in_memory import (
    InMemoryHindsightAdapter,
)


@pytest.mark.asyncio
async def test_seeded_bank_returns_filtered_entries() -> None:
    seed = {
        "iguanatrader-research-tA": [
            "[brief_summary] AAPL Q4 strong earnings",
            "[brief_summary] MSFT cloud revenue growth",
            "[brief_summary] GOOGL search market share",
        ],
    }
    adapter = InMemoryHindsightAdapter(seed=seed)
    result = await adapter.recall(
        bank="iguanatrader-research-tA",
        query="AAPL",
        limit=10,
    )
    assert len(result) == 1
    assert "AAPL" in result[0]


@pytest.mark.asyncio
async def test_empty_bank_returns_empty_list() -> None:
    adapter = InMemoryHindsightAdapter()
    result = await adapter.recall(
        bank="iguanatrader-research-missing",
        query="foo",
        limit=10,
    )
    assert result == []


@pytest.mark.asyncio
async def test_retain_appends_to_bank_then_recall_returns_it() -> None:
    adapter = InMemoryHindsightAdapter()
    await adapter.retain(
        bank="iguanatrader-research-tB",
        kind="brief_summary",
        content="TSLA delivery numbers",
        metadata={"version": 1},
    )
    result = await adapter.recall(
        bank="iguanatrader-research-tB",
        query="TSLA",
        limit=5,
    )
    assert len(result) == 1
    assert "TSLA" in result[0]
    assert result[0].startswith("[brief_summary]")
