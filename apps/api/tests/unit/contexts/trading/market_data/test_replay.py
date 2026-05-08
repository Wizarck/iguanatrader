"""Unit tests for :class:`MarketDataReplayService` (slice market-data-replay)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from iguanatrader.contexts.trading.market_data.in_memory import (
    InMemoryMarketDataAdapter,
)
from iguanatrader.contexts.trading.market_data.replay import (
    MarketDataReplayService,
)
from iguanatrader.contexts.trading.ports import (
    Bar,
    BarHistory,
    Proposal,
    StrategyConfigSnapshot,
)


def _seed_bars(n: int = 30) -> list[Bar]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    out: list[Bar] = []
    for i in range(n):
        out.append(
            Bar(
                timestamp=base + timedelta(days=i),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal(str(100 + i)),
                volume=Decimal("1000"),
            )
        )
    return out


class _StubConfig:
    def __init__(self, *, symbol: str, kind: str = "donchian_atr") -> None:
        self.id = uuid4()
        self.tenant_id = uuid4()
        self.strategy_kind = kind
        self.symbol = symbol
        self.params: dict[str, Any] = {"lookback": 20}
        self.enabled = True
        self.version = 1


class _SignalStrategy:
    """Strategy stub returning a fixed Proposal."""

    def evaluate(
        self,
        symbol: str,
        bars: BarHistory,
        config: StrategyConfigSnapshot,
    ) -> Proposal | None:
        return Proposal(
            tenant_id=config.tenant_id,
            strategy_config_id=config.id,
            symbol=symbol,
            side="buy",
            quantity=Decimal("10"),
            entry_price_indicative=Decimal("100"),
            stop_price=Decimal("95"),
            confidence_score=Decimal("0.5"),
            reasoning={"why": "test"},
            mode="paper",
            correlation_id=uuid4(),
        )


class _NoSignalStrategy:
    def evaluate(
        self,
        symbol: str,
        bars: BarHistory,
        config: StrategyConfigSnapshot,
    ) -> Proposal | None:
        return None


@pytest.mark.asyncio
async def test_replay_with_signal_returns_would_propose_true() -> None:
    md = InMemoryMarketDataAdapter(seed={"AAPL": _seed_bars()})
    cfg = _StubConfig(symbol="AAPL")
    repo = AsyncMock()
    repo.list_enabled_for_symbol = AsyncMock(return_value=[cfg])

    async def _resolver(_id: Any) -> Any:
        return _SignalStrategy()

    service = MarketDataReplayService(
        market_data_port=md,
        strategy_config_repo=repo,
        strategy_resolver=_resolver,
    )
    result = await service.replay(
        symbols=["AAPL"],
        routine="midday",
        as_of=datetime(2026, 1, 30, tzinfo=UTC),
    )
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.would_propose is True
    assert row.side == "buy"
    assert row.quantity == Decimal("10")
    assert row.entry_price == Decimal("100")
    assert row.stop_price == Decimal("95")


@pytest.mark.asyncio
async def test_replay_without_signal_returns_no_signal_rationale() -> None:
    md = InMemoryMarketDataAdapter(seed={"AAPL": _seed_bars()})
    cfg = _StubConfig(symbol="AAPL")
    repo = AsyncMock()
    repo.list_enabled_for_symbol = AsyncMock(return_value=[cfg])

    async def _resolver(_id: Any) -> Any:
        return _NoSignalStrategy()

    service = MarketDataReplayService(
        market_data_port=md,
        strategy_config_repo=repo,
        strategy_resolver=_resolver,
    )
    result = await service.replay(
        symbols=["AAPL"],
        routine="midday",
        as_of=datetime(2026, 1, 30, tzinfo=UTC),
    )
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.would_propose is False
    assert row.rationale == "<no signal>"


@pytest.mark.asyncio
async def test_replay_rejects_unknown_routine() -> None:
    repo = AsyncMock()
    md = InMemoryMarketDataAdapter(seed={})

    async def _resolver(_id: Any) -> Any:
        return _NoSignalStrategy()

    service = MarketDataReplayService(
        market_data_port=md,
        strategy_config_repo=repo,
        strategy_resolver=_resolver,
    )
    with pytest.raises(ValueError, match="Unknown routine"):
        await service.replay(
            symbols=["AAPL"],
            routine="not-a-routine",
            as_of=datetime(2026, 1, 30, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_replay_handles_symbol_with_no_enabled_configs() -> None:
    md = InMemoryMarketDataAdapter(seed={"AAPL": _seed_bars()})
    repo = AsyncMock()
    repo.list_enabled_for_symbol = AsyncMock(return_value=[])

    async def _resolver(_id: Any) -> Any:
        return _NoSignalStrategy()

    service = MarketDataReplayService(
        market_data_port=md,
        strategy_config_repo=repo,
        strategy_resolver=_resolver,
    )
    result = await service.replay(
        symbols=["AAPL"],
        routine="midday",
        as_of=datetime(2026, 1, 30, tzinfo=UTC),
    )
    assert len(result.rows) == 1
    assert result.rows[0].would_propose is False
    assert "no enabled configs" in result.rows[0].rationale


@pytest.mark.asyncio
async def test_as_of_filter_clips_bars_to_historical_window() -> None:
    md = InMemoryMarketDataAdapter(seed={"AAPL": _seed_bars(30)})
    cfg = _StubConfig(symbol="AAPL")
    repo = AsyncMock()
    repo.list_enabled_for_symbol = AsyncMock(return_value=[cfg])

    captured: list[BarHistory] = []

    class _CaptureStrategy:
        def evaluate(
            self,
            symbol: str,
            bars: BarHistory,
            config: StrategyConfigSnapshot,
        ) -> Proposal | None:
            captured.append(bars)
            return None

    async def _resolver(_id: Any) -> Any:
        return _CaptureStrategy()

    service = MarketDataReplayService(
        market_data_port=md,
        strategy_config_repo=repo,
        strategy_resolver=_resolver,
    )
    # as_of mid-window: should only see bars on or before day 10.
    target = datetime(2026, 1, 11, tzinfo=UTC)
    await service.replay(
        symbols=["AAPL"],
        routine="midday",
        as_of=target,
    )
    assert len(captured) == 1
    seen = captured[0]
    assert all(b.timestamp <= target for b in seen.bars)
