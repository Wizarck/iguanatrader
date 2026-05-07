"""Unit tests for :class:`DBMarketDataAdapter` (slice T4-followup-market-data §9.1.2).

Uses a real sqlite session via the existing ``engine`` + ``session_factory``
fixture pattern (mirroring ``apps/api/tests/unit/contexts/approval/test_timeout_sweeper.py``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.trading.market_data import MarketDataNotAvailableError
from iguanatrader.contexts.trading.market_data.db import DBMarketDataAdapter
from iguanatrader.contexts.trading.market_data.models import MarketDataBar
from iguanatrader.persistence import (
    Tenant,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.shared.contextvars import session_var, with_tenant_context
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


@pytest.fixture(autouse=True)
def _listeners() -> Iterator[None]:
    register_global_listeners()
    try:
        yield
    finally:
        unregister_global_listeners()


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    db_path = tmp_path / "md_db.db"
    eng = engine_factory(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def sf(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return session_factory(engine)


async def _seed_bars(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    symbol: str,
    n: int,
    start_offset_days: int = 0,
) -> None:
    """INSERT n daily bars for the given tenant/symbol."""
    async with with_tenant_context(tenant_id), sf() as s:
        s.add(Tenant(id=tenant_id, name=f"t-{tenant_id}", feature_flags={}))
        await s.commit()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    async with with_tenant_context(tenant_id), sf() as s:
        for d in range(n):
            s.add(
                MarketDataBar(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    symbol=symbol,
                    timeframe="1d",
                    ts=base + timedelta(days=start_offset_days + d),
                    open=Decimal("100"),
                    high=Decimal("101"),
                    low=Decimal("99"),
                    close=Decimal(str(100 + d)),
                    volume=1_000_000 + d,
                    source="ibkr",
                    fetched_at=datetime.now(UTC),
                )
            )
        await s.commit()


@pytest.mark.asyncio
async def test_empty_table_raises_market_data_not_available(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = uuid4()
    async with with_tenant_context(tenant_id), sf() as s:
        s.add(Tenant(id=tenant_id, name="t", feature_flags={}))
        await s.commit()
    async with with_tenant_context(tenant_id), sf() as s:
        session_var.set(s)
        adapter = DBMarketDataAdapter()
        with pytest.raises(MarketDataNotAvailableError):
            await adapter.get_bars(symbol="AAPL", timeframe="1d", lookback_bars=10)


@pytest.mark.asyncio
async def test_returns_last_n_sorted_ascending(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = uuid4()
    await _seed_bars(sf, tenant_id=tenant_id, symbol="AAPL", n=250)

    async with with_tenant_context(tenant_id), sf() as s:
        session_var.set(s)
        adapter = DBMarketDataAdapter()
        history = await adapter.get_bars(
            symbol="AAPL",
            timeframe="1d",
            lookback_bars=200,
        )

    assert history.symbol == "AAPL"
    assert len(history.bars) == 200
    # Ascending: first bar's ts must be earlier than last.
    assert history.bars[0].timestamp < history.bars[-1].timestamp
    # Last 200 of 250: closes 50..249.
    assert history.bars[0].close == Decimal("150")
    assert history.bars[-1].close == Decimal("249")


@pytest.mark.asyncio
async def test_tenant_isolation_filters_other_tenants_rows(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tenant_a = uuid4()
    tenant_b = uuid4()
    await _seed_bars(sf, tenant_id=tenant_a, symbol="AAPL", n=10)
    await _seed_bars(sf, tenant_id=tenant_b, symbol="AAPL", n=20, start_offset_days=100)

    # Tenant B reads → must see only its own 20 rows.
    async with with_tenant_context(tenant_b), sf() as s:
        session_var.set(s)
        adapter = DBMarketDataAdapter()
        history = await adapter.get_bars(
            symbol="AAPL",
            timeframe="1d",
            lookback_bars=100,
        )

    assert len(history.bars) == 20
    # Tenant A's bars use the [base..base+9] window; tenant B's use
    # [base+100..base+119]. Tenant B's first ts must therefore be after
    # 2026-04-09.
    assert history.bars[0].timestamp >= datetime(2026, 4, 1, tzinfo=UTC)
