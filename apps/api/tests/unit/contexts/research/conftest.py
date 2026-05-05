"""Fixtures for research context unit tests.

Each test gets:

* Per-test on-disk SQLite (tmp_path) with the L2 trigger DDL emitted by the
  migration's helper functions — same DDL the real ``alembic upgrade``
  produces. We can't run the full migration here because slice-3
  ``0001_initial_schema`` + slice-4 ``0002_users_role_enum`` don't ship
  ``research_*`` tables; instead we ``Base.metadata.create_all`` and then
  emit the L2 triggers via the migration's helper functions directly.
* Tenant + append-only listeners registered.
* Fixed tenant_id_var via ``with_tenant_context``.
* :class:`ResearchRepository` with ``payload_root`` pointing under tmp_path.
* Seeded ``ResearchSource`` + ``SymbolUniverse`` + ``Tenant`` row so tests
  can insert facts without re-doing the boilerplate every time.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.research.models import ResearchSource, SymbolUniverse
from iguanatrader.contexts.research.repository import ResearchRepository
from iguanatrader.migrations._research_trigger_helpers import (
    SQLITE_TRIGGER_SQL,
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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

if sys.platform == "win32":  # pragma: no cover — Windows-only event-loop quirk
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    db_path = tmp_path / "ig_research_test.db"
    return f"sqlite+aiosqlite:///{db_path.as_posix()}"


@pytest.fixture
async def engine(db_url: str) -> AsyncIterator[AsyncEngine]:
    eng = engine_factory(db_url)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def session_factory_fx(
    engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Session factory + L2 triggers for append-only research tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Emit the L2 triggers directly — same DDL the migration produces.
        # We use the migration's SQLite-branch helper text so the tests
        # exercise the exact trigger surface that production ships.
        for sql in SQLITE_TRIGGER_SQL:
            await conn.execute(text(sql))
    try:
        yield session_factory(engine)
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(autouse=True)
def _register_listeners() -> Iterator[None]:
    register_global_listeners()
    try:
        yield
    finally:
        unregister_global_listeners()


@pytest.fixture
def tenant_id() -> UUID:
    return uuid4()


@pytest.fixture
async def seeded_world(
    session_factory_fx: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
) -> dict[str, Any]:
    """Seed Tenant + ResearchSource + SymbolUniverse rows.

    Returns dict with ``tenant_id``, ``source_id``, ``symbol``, ``universe_id``.
    """
    universe_id = uuid4()
    async with session_factory_fx() as s:
        # Tenant is cross-tenant (Tenant.__tenant_scoped__ == False) so the
        # listener skips it; insert without tenant_id_var set.
        s.add(Tenant(id=tenant_id, name="research-test-tenant", feature_flags={}))
        s.add(
            ResearchSource(
                id="sec_edgar",
                display_name="SEC EDGAR Official APIs",
                tier=1,
                pit_class="A",
                enabled=True,
            )
        )
        await s.commit()

    async with with_tenant_context(tenant_id), session_factory_fx() as s:
        s.add(
            SymbolUniverse(
                id=universe_id,
                tenant_id=tenant_id,
                symbol="AAPL",
                exchange="NASDAQ",
            )
        )
        await s.commit()

    return {
        "tenant_id": tenant_id,
        "source_id": "sec_edgar",
        "symbol": "AAPL",
        "universe_id": universe_id,
    }


@pytest.fixture
async def repository(tmp_path: Path) -> AsyncIterator[ResearchRepository]:
    """Build a :class:`ResearchRepository` with a tmp_path payload root."""
    repo = ResearchRepository(payload_root=tmp_path / "cache")
    yield repo


@pytest.fixture
async def with_session(
    session_factory_fx: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Bind a session to ``session_var`` so :class:`ResearchRepository` can read it."""
    async with session_factory_fx() as s:
        token = session_var.set(s)
        try:
            yield s
        finally:
            session_var.reset(token)
