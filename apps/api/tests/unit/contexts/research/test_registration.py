"""Unit tests for ``ensure_symbol_registered`` (slice research-ad-hoc-mode).

Covers the auto-registration helper used by ``BriefService.refresh`` to
make ad-hoc research possible without a pre-existing CLI bootstrap.

Invariants:

1. First call for ``(tenant, symbol)`` inserts both rows and reports
   ``created=True``.
2. Second call for the same ``(tenant, symbol)`` returns the SAME ids
   with ``created=False`` (idempotent).
3. Concurrent first-time inserts from two tenants for the SAME symbol
   each get their own ids (tenant isolation).
4. Defaults are applied when the caller does not override
   (``tier=primary``, ``brief_refresh_schedule=manual``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from iguanatrader.contexts.research.models import SymbolUniverse, WatchlistConfig
from iguanatrader.contexts.research.registration import (
    DEFAULT_SCHEDULE,
    DEFAULT_TIER,
    ensure_symbol_registered,
)
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
    db_path = tmp_path / "ig_registration.db"
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


@pytest.mark.asyncio
async def test_first_call_inserts_both_rows(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name="t1", feature_flags={}))
        await s.commit()
    async with with_tenant_context(tid), sf() as session:
        session_var.set(session)
        outcome = await ensure_symbol_registered(
            session=session,
            tenant_id=tid,
            symbol="NVDA",
        )
        await session.commit()
        assert outcome.created is True

        sym = (
            await session.execute(sa.select(SymbolUniverse).where(SymbolUniverse.symbol == "NVDA"))
        ).scalar_one()
        assert sym.tenant_id == tid

        wl = (
            await session.execute(
                sa.select(WatchlistConfig).where(WatchlistConfig.symbol_universe_id == sym.id)
            )
        ).scalar_one()
        assert wl.tier == DEFAULT_TIER
        assert wl.brief_refresh_schedule == DEFAULT_SCHEDULE


@pytest.mark.asyncio
async def test_second_call_is_idempotent(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name="t2", feature_flags={}))
        await s.commit()
    async with with_tenant_context(tid), sf() as session:
        session_var.set(session)
        first = await ensure_symbol_registered(
            session=session,
            tenant_id=tid,
            symbol="AMD",
        )
        await session.commit()
        second = await ensure_symbol_registered(
            session=session,
            tenant_id=tid,
            symbol="AMD",
        )
        await session.commit()
        assert first.created is True
        assert second.created is False
        assert first.symbol_universe_id == second.symbol_universe_id
        assert first.watchlist_config_id == second.watchlist_config_id


@pytest.mark.asyncio
async def test_two_tenants_get_separate_rows_for_same_symbol(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid_a = uuid4()
    tid_b = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid_a, name="ta", feature_flags={}))
        s.add(Tenant(id=tid_b, name="tb", feature_flags={}))
        await s.commit()

    async with with_tenant_context(tid_a), sf() as session:
        session_var.set(session)
        a = await ensure_symbol_registered(session=session, tenant_id=tid_a, symbol="SPY")
        await session.commit()

    async with with_tenant_context(tid_b), sf() as session:
        session_var.set(session)
        b = await ensure_symbol_registered(session=session, tenant_id=tid_b, symbol="SPY")
        await session.commit()

    assert a.symbol_universe_id != b.symbol_universe_id
    assert a.watchlist_config_id != b.watchlist_config_id
