"""#31: ``tenant_admin`` feature-flag read/write round-trip.

The ``/lock`` operator pause depends on ``set_feature_flag`` actually
persisting ``approvals_paused`` — the module did not exist before, so the
command was a silent no-op. These tests pin the writer/reader contract:
a written flag reads back True, and ``set_feature_flag`` RAISES (never
silently drops) when it cannot resolve a session or tenant.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from iguanatrader.contexts.observability.tenant_admin import (
    get_feature_flag,
    set_feature_flag,
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
    eng = engine_factory(f"sqlite+aiosqlite:///{(tmp_path / 'flags.db').as_posix()}")
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
async def test_set_then_get_feature_flag_round_trip(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name="t", feature_flags={}))
        await s.commit()

    async with with_tenant_context(tid), sf() as session:
        session_var.set(session)
        # Default when unset.
        assert await get_feature_flag("approvals_paused", False) is False
        # Write, then read back the persisted value.
        await set_feature_flag("approvals_paused", True)
        assert await get_feature_flag("approvals_paused", False) is True
        # Clear it again.
        await set_feature_flag("approvals_paused", False)
        assert await get_feature_flag("approvals_paused", True) is False


@pytest.mark.asyncio
async def test_set_feature_flag_raises_without_session() -> None:
    # No session bound → a write MUST raise, never silently succeed.
    session_var.set(None)
    with pytest.raises(RuntimeError):
        await set_feature_flag("approvals_paused", True, tenant_id=uuid4())


@pytest.mark.asyncio
async def test_get_feature_flag_returns_default_without_session() -> None:
    session_var.set(None)
    assert await get_feature_flag("approvals_paused", "fallback", tenant_id=uuid4()) == "fallback"
