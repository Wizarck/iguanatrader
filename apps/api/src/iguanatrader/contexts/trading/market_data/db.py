"""DB-backed :class:`MarketDataPort` implementation (production read).

SELECT-only adapter. Reads its session lazily from
:data:`iguanatrader.shared.contextvars.session_var`. Tenant scoping is
automatic via the slice-3 ``tenant_listener`` (the WHERE-clause is
injected on every SELECT).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select

from iguanatrader.contexts.trading.market_data import MarketDataNotAvailableError
from iguanatrader.contexts.trading.market_data.models import MarketDataBar
from iguanatrader.contexts.trading.ports import Bar, BarHistory
from iguanatrader.shared.contextvars import session_var


class DBMarketDataAdapter:
    """SELECT from ``market_data_bars`` populated by the IBKR ingestor."""

    async def count_sessions_since(
        self,
        *,
        symbol: str,
        since: datetime,
    ) -> int | None:
        """Count market (trading) sessions held since ``since`` for ``symbol``.

        Each ``1d`` bar in ``market_data_bars`` exists only for a real trading
        session, so the count of daily bars with ``ts >= since`` is the number
        of market days the position has been open — inheriting the exchange
        calendar (weekends + holidays) for free, with no calendar library.

        ``since`` should be the position's ``opened_at`` floored to its UTC
        date so the open day counts as day 1 (the comparison is a plain ``ts``
        bound — NOT ``date(ts)`` — to avoid the SQLite/Postgres timezone
        divergence on date extraction).

        Returns ``None`` when no daily bars exist for the symbol at all (the
        caller renders "—" rather than a misleading 0); a real 0 sessions (e.g.
        opened today before the session's bar lands) returns 0.
        """
        session = session_var.get()
        if session is None:
            raise LookupError(
                "session_var not set; cannot read market_data_bars. "
                "Caller must run inside a session-scoped context."
            )
        any_bar = await session.scalar(
            select(MarketDataBar.id)
            .where(MarketDataBar.symbol == symbol)
            .where(MarketDataBar.timeframe == "1d")
            .limit(1)
        )
        if any_bar is None:
            return None
        count = await session.scalar(
            select(func.count())
            .select_from(MarketDataBar)
            .where(MarketDataBar.symbol == symbol)
            .where(MarketDataBar.timeframe == "1d")
            .where(MarketDataBar.ts >= since)
        )
        return int(count or 0)

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
                # MarketDataBar.ts is DateTime(timezone=True); Postgres
                # preserves tz, SQLite strips it on round-trip. Coerce to
                # UTC-aware so downstream callers can mix-compare freely.
                timestamp=row.ts if row.ts.tzinfo is not None else row.ts.replace(tzinfo=UTC),
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
