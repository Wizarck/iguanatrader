"""Unit tests for :class:`TradeJournalWriter`."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from iguanatrader.contexts.research.synthesis.llm_client import (
    FakeLLMClient,
    LLMCompletion,
)
from iguanatrader.contexts.trading.journaling import (
    JOURNAL_MAX_TOKENS,
    TradeJournalWriter,
)


class _RecordingFake(FakeLLMClient):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        prompt: str,
        *,
        model: str,
        replay_key: str | None,
        max_tokens: int,
        langfuse_application: str = "iguanatrader-synthesis",
    ) -> LLMCompletion:
        self.calls.append(
            {
                "prompt": prompt,
                "model": model,
                "max_tokens": max_tokens,
                "langfuse_application": langfuse_application,
            }
        )
        return LLMCompletion(
            text=(
                "## What this trade aimed to do\n\n"
                "Long SPY on a donchian breakout.\n\n"
                "## How it went\n\nStopped out in 3 bars.\n\n"
                "## Lesson\n\nBreakouts in low-volume sessions fail more often."
            ),
            tokens_input=80,
            tokens_output=40,
            cached=False,
            model=model,
            replay_key=replay_key,
        )


@pytest.mark.asyncio
async def test_write_passes_journal_application_tag() -> None:
    fake = _RecordingFake()
    writer = TradeJournalWriter(fake)

    result = await writer.write(
        trade_id="22222222-2222-2222-2222-222222222222",
        symbol="SPY",
        side="buy",
        quantity=Decimal("10"),
        mode="paper",
        opened_at=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
        closed_at=datetime(2026, 5, 15, 10, 12, tzinfo=UTC),
        exit_reason="stop",
        realised_pnl=Decimal("-12.50"),
    )

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["langfuse_application"] == "iguanatrader-journal"
    assert call["max_tokens"] == JOURNAL_MAX_TOKENS
    assert "SPY" in call["prompt"]
    assert "stop" in call["prompt"]
    assert "Lesson" in result.narrative


@pytest.mark.asyncio
async def test_write_handles_open_trade_gracefully() -> None:
    """Defensive: the route layer should never call writer on an open trade,
    but if it does (e.g. via direct service usage), the prompt should
    still render without raising."""
    fake = _RecordingFake()
    writer = TradeJournalWriter(fake)

    result = await writer.write(
        trade_id="x",
        symbol="SPY",
        side="buy",
        quantity=Decimal("1"),
        mode="paper",
        opened_at=datetime(2026, 5, 15, 10, 0, tzinfo=UTC),
        closed_at=None,
        exit_reason=None,
        realised_pnl=None,
    )
    assert "still open" in fake.calls[0]["prompt"]
    assert "unknown" in fake.calls[0]["prompt"]
    assert result.narrative
