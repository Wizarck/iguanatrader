"""#26: L2 append-only triggers block RAW (out-of-ORM) mutation of the
pure-ledger trading tables (``fills``, ``equity_snapshots``).

The L1 ``before_flush`` listener only guards ORM flushes; a raw
``session.execute(text("UPDATE ..."))`` bypasses it. These triggers are
the database-level backstop. ``Base.metadata.create_all`` does not model
triggers, so the test re-emits the SQLite trigger DDL exactly as the
migration does (mirrors the research-table conftest pattern).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from iguanatrader.contexts.trading.models import EquitySnapshot
from iguanatrader.migrations._trading_trigger_helpers import SQLITE_TRADING_TRIGGER_SQL
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
    eng = engine_factory(f"sqlite+aiosqlite:///{(tmp_path / 'l2.db').as_posix()}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Re-emit the L2 triggers (create_all doesn't model triggers).
        for sql in SQLITE_TRADING_TRIGGER_SQL:
            await conn.execute(sa.text(sql))
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def sf(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return session_factory(engine)


async def _seed_snapshot(sf: async_sessionmaker[AsyncSession], tid: UUID) -> object:
    async with sf() as s:
        s.add(Tenant(id=tid, name="t", feature_flags={}))
        await s.commit()
    snap_id = uuid4()
    async with with_tenant_context(tid), sf() as s:
        s.add(
            EquitySnapshot(
                id=snap_id,
                tenant_id=tid,
                mode="paper",
                account_equity=Decimal("1000"),
                cash_balance=Decimal("1000"),
                snapshot_kind="daily",
            )
        )
        await s.commit()
    return snap_id


@pytest.mark.asyncio
async def test_raw_update_on_equity_snapshots_is_blocked(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid = uuid4()
    await _seed_snapshot(sf, tid)
    async with with_tenant_context(tid), sf() as session:
        session_var.set(session)
        # No WHERE: the single seeded row is enough to fire the BEFORE
        # UPDATE trigger (avoids dialect-specific UUID id formatting).
        with pytest.raises(Exception, match="append-only"):
            await session.execute(sa.text("UPDATE equity_snapshots SET cash_balance = 1"))


@pytest.mark.asyncio
async def test_raw_delete_on_equity_snapshots_is_blocked(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid = uuid4()
    await _seed_snapshot(sf, tid)
    async with with_tenant_context(tid), sf() as session:
        session_var.set(session)
        with pytest.raises(Exception, match="append-only"):
            await session.execute(sa.text("DELETE FROM equity_snapshots"))
