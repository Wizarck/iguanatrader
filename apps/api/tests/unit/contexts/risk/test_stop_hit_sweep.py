"""Unit tests for the stop-hit + target-hit sweep (slice
``exit-classification-stop-hit-sweep``).

Pure-unit tests for the side-aware comparators + a thin integration
test exercising the SQLAlchemy-join → market-data → bus-publish path
with in-memory fakes.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from iguanatrader.contexts.risk.stop_hit_sweep import (
    StopHitSweepService,
    _is_stop_hit,
    _is_target_hit,
)
from iguanatrader.contexts.trading.events import CloseTradeRequested
from iguanatrader.contexts.trading.ports import Bar, BarHistory

# ---------------------------------------------------------------------------
# Pure comparator helpers
# ---------------------------------------------------------------------------


def test_long_stop_hit_when_close_at_or_below_stop() -> None:
    assert _is_stop_hit(side="buy", close=Decimal("99.99"), stop=Decimal("100")) is True
    assert _is_stop_hit(side="buy", close=Decimal("100.00"), stop=Decimal("100")) is True
    assert _is_stop_hit(side="buy", close=Decimal("100.01"), stop=Decimal("100")) is False


def test_short_stop_hit_when_close_at_or_above_stop() -> None:
    assert _is_stop_hit(side="sell", close=Decimal("100.01"), stop=Decimal("100")) is True
    assert _is_stop_hit(side="sell", close=Decimal("100.00"), stop=Decimal("100")) is True
    assert _is_stop_hit(side="sell", close=Decimal("99.99"), stop=Decimal("100")) is False


def test_long_target_hit_when_close_at_or_above_target() -> None:
    assert _is_target_hit(side="buy", close=Decimal("120.01"), target=Decimal("120")) is True
    assert _is_target_hit(side="buy", close=Decimal("120.00"), target=Decimal("120")) is True
    assert _is_target_hit(side="buy", close=Decimal("119.99"), target=Decimal("120")) is False


def test_short_target_hit_when_close_at_or_below_target() -> None:
    assert _is_target_hit(side="sell", close=Decimal("79.99"), target=Decimal("80")) is True
    assert _is_target_hit(side="sell", close=Decimal("80.00"), target=Decimal("80")) is True
    assert _is_target_hit(side="sell", close=Decimal("80.01"), target=Decimal("80")) is False


def test_unknown_side_never_fires() -> None:
    """Defensive guard: a malformed ``side`` value never closes a trade."""
    assert _is_stop_hit(side="hold", close=Decimal("0"), stop=Decimal("100")) is False
    assert _is_target_hit(side="hold", close=Decimal("999"), target=Decimal("100")) is False


# ---------------------------------------------------------------------------
# Sweep integration with fake session + market-data + bus
# ---------------------------------------------------------------------------


@dataclass
class _OpenTrade:
    """Row shape returned by the fake session's `execute().all()`."""

    id: UUID
    tenant_id: UUID
    symbol: str
    side: str
    stop_price: Decimal
    target_price: Decimal | None

    def as_row(self) -> tuple[Any, ...]:
        return (
            self.id,
            self.tenant_id,
            self.symbol,
            self.side,
            self.stop_price,
            self.target_price,
        )


class _FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows


class _FakeSession:
    """SQLAlchemy-shaped fake: ``execute(stmt)`` returns canned rows."""

    def __init__(self, trades: list[_OpenTrade]) -> None:
        self._trades = trades

    async def execute(self, _stmt: Any) -> _FakeResult:
        return _FakeResult([t.as_row() for t in self._trades])


class _FakeMarketData:
    """Returns a single-bar history with the configured close per symbol."""

    def __init__(self, closes: dict[str, Decimal | None]) -> None:
        # None ⇒ simulate empty bars (no-bars skip path).
        self._closes = closes

    async def get_bars(
        self,
        *,
        symbol: str,
        timeframe: str,
        lookback_bars: int,
        as_of: datetime | None = None,
    ) -> BarHistory:
        del timeframe, lookback_bars, as_of
        close = self._closes.get(symbol)
        if close is None:
            return BarHistory(symbol=symbol, bars=[])
        bar = Bar(
            timestamp=datetime(2026, 5, 18, tzinfo=UTC),
            open=close,
            high=close,
            low=close,
            close=close,
            volume=Decimal("1000"),
        )
        return BarHistory(symbol=symbol, bars=[bar])


class _RecordingBus:
    def __init__(self) -> None:
        self.published: list[Any] = []

    async def publish(self, event: Any) -> None:
        self.published.append(event)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_sweep_emits_close_on_long_stop_hit() -> None:
    trade = _OpenTrade(
        id=uuid4(),
        tenant_id=uuid4(),
        symbol="NVDA",
        side="buy",
        stop_price=Decimal("400"),
        target_price=Decimal("500"),
    )
    bus = _RecordingBus()
    service = StopHitSweepService(
        session=_FakeSession([trade]),  # type: ignore[arg-type]
        market_data_port=_FakeMarketData({"NVDA": Decimal("399.99")}),
        bus=bus,  # type: ignore[arg-type]
    )
    result = _run(service.sweep())

    assert result.trades_evaluated == 1
    assert result.stop_hits_emitted == 1
    assert result.target_hits_emitted == 0
    assert len(bus.published) == 1
    event = bus.published[0]
    assert isinstance(event, CloseTradeRequested)
    assert event.trade_id == trade.id
    assert event.reason == "stop"


def test_sweep_emits_close_on_short_target_hit() -> None:
    trade = _OpenTrade(
        id=uuid4(),
        tenant_id=uuid4(),
        symbol="ZZZ",
        side="sell",
        stop_price=Decimal("120"),  # not hit
        target_price=Decimal("80"),
    )
    bus = _RecordingBus()
    service = StopHitSweepService(
        session=_FakeSession([trade]),  # type: ignore[arg-type]
        market_data_port=_FakeMarketData({"ZZZ": Decimal("79")}),
        bus=bus,  # type: ignore[arg-type]
    )
    result = _run(service.sweep())

    assert result.stop_hits_emitted == 0
    assert result.target_hits_emitted == 1
    assert bus.published[0].reason == "target"


def test_sweep_skips_trade_with_no_bars() -> None:
    """Empty market-data response increments the skipped counter and
    does NOT publish a close event."""
    trade = _OpenTrade(
        id=uuid4(),
        tenant_id=uuid4(),
        symbol="ILLIQ",
        side="buy",
        stop_price=Decimal("10"),
        target_price=Decimal("20"),
    )
    bus = _RecordingBus()
    service = StopHitSweepService(
        session=_FakeSession([trade]),  # type: ignore[arg-type]
        market_data_port=_FakeMarketData({"ILLIQ": None}),
        bus=bus,  # type: ignore[arg-type]
    )
    result = _run(service.sweep())

    assert result.trades_evaluated == 1
    assert result.stop_hits_emitted == 0
    assert result.target_hits_emitted == 0
    assert bus.published == []


def test_sweep_no_target_when_target_price_is_null() -> None:
    """A proposal with target_price=NULL (low-confidence path) must NOT
    fire a target-hit even on a very favourable bar."""
    trade = _OpenTrade(
        id=uuid4(),
        tenant_id=uuid4(),
        symbol="WIN",
        side="buy",
        stop_price=Decimal("50"),
        target_price=None,
    )
    bus = _RecordingBus()
    service = StopHitSweepService(
        session=_FakeSession([trade]),  # type: ignore[arg-type]
        market_data_port=_FakeMarketData({"WIN": Decimal("999")}),
        bus=bus,  # type: ignore[arg-type]
    )
    result = _run(service.sweep())

    assert result.stop_hits_emitted == 0
    assert result.target_hits_emitted == 0
    assert bus.published == []


def test_sweep_continues_on_per_trade_exception() -> None:
    """A market-data error for trade A must not abort the evaluation of trade B."""

    class _PartiallyFailingMarketData:
        async def get_bars(self, **kwargs: Any) -> BarHistory:
            symbol = kwargs["symbol"]
            if symbol == "BROKEN":
                raise RuntimeError("provider 502")
            bar = Bar(
                timestamp=datetime(2026, 5, 18, tzinfo=UTC),
                open=Decimal("10"),
                high=Decimal("10"),
                low=Decimal("10"),
                close=Decimal("9"),
                volume=Decimal("100"),
            )
            return BarHistory(symbol=symbol, bars=[bar])

    broken = _OpenTrade(
        id=uuid4(),
        tenant_id=uuid4(),
        symbol="BROKEN",
        side="buy",
        stop_price=Decimal("100"),
        target_price=None,
    )
    healthy = _OpenTrade(
        id=uuid4(),
        tenant_id=uuid4(),
        symbol="HEALTHY",
        side="buy",
        stop_price=Decimal("10"),  # close=9 ⇒ stop hit
        target_price=None,
    )
    bus = _RecordingBus()
    service = StopHitSweepService(
        session=_FakeSession([broken, healthy]),  # type: ignore[arg-type]
        market_data_port=_PartiallyFailingMarketData(),
        bus=bus,  # type: ignore[arg-type]
    )
    result = _run(service.sweep())

    assert result.trades_evaluated == 2
    assert result.trades_skipped_no_bars == 1  # the BROKEN one
    assert result.stop_hits_emitted == 1
    assert len(bus.published) == 1
    assert bus.published[0].trade_id == healthy.id
