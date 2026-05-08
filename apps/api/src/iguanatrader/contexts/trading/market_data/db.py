"""DB-backed :class:`MarketDataPort` implementation (production read).

SELECT-only adapter. Reads its session lazily from
:data:`iguanatrader.shared.contextvars.session_var`. Tenant scoping is
automatic via the slice-3 ``tenant_listener`` (the WHERE-clause is
injected on every SELECT).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import select

from iguanatrader.contexts.trading.market_data import MarketDataNotAvailableError
from iguanatrader.contexts.trading.market_data.models import MarketDataBar
from iguanatrader.contexts.trading.ports import Bar, BarHistory
from iguanatrader.shared.contextvars import session_var


class DBMarketDataAdapter:
    """SELECT from ``market_data_bars`` populated by the IBKR ingestor."""

    async def get_bars(
        self,
        *,
        symbol: str,
        timeframe: Literal["1d", "1h", "1m"],
        lookback_bars: int,
        as_of: datetime | None = None,
    ) -> BarHistory:
        session = session_var.get()
        if session is None:
            raise LookupError(
                "session_var not set; cannot read market_data_bars. "
                "Caller must run inside a session-scoped context "
                "(daemon's async-with sessionmaker block, request scope, "
                "or with_session_context())."
            )
        stmt = (
            select(MarketDataBar)
            .where(MarketDataBar.symbol == symbol)
            .where(MarketDataBar.timeframe == timeframe)
        )
        if as_of is not None:
            stmt = stmt.where(MarketDataBar.ts <= as_of)
        stmt = stmt.order_by(MarketDataBar.ts.desc()).limit(lookback_bars)
        result = await session.execute(stmt)
        rows = list(result.scalars().all())
        if not rows:
            raise MarketDataNotAvailableError(
                detail=(
                    f"No bars in DB for symbol={symbol!r}, timeframe={timeframe!r}. "
                    "Run ``iguanatrader market-data backfill --symbol "
                    f"{symbol}`` to populate."
                ),
            )
        rows.reverse()  # caller expects ascending ts
        bars = tuple(
            Bar(
                timestamp=row.ts,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=Decimal(row.volume),
            )
            for row in rows
        )
        return BarHistory(symbol=symbol, bars=bars)


__all__ = ["DBMarketDataAdapter"]
