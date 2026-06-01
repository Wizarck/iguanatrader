"""#43: kill-switch activation dedup is derived atomically from the cache
upsert rowcount, not from a separate dirty pre-read.

A second activation still records an audit event row (every attempt is
captured) but publishes ``RiskKillSwitchActivated`` exactly once — and a
no-op deactivate of a never-activated tenant publishes nothing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from iguanatrader.contexts.risk.events import (
    RiskKillSwitchActivated,
    RiskKillSwitchDeactivated,
)
from iguanatrader.contexts.risk.orm import KillSwitchEventORM
from iguanatrader.contexts.risk.repository import RiskRepository
from iguanatrader.contexts.risk.service import RiskService
from iguanatrader.persistence import (
    Tenant,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.shared.contextvars import session_var, with_tenant_context
from iguanatrader.shared.messagebus import MessageBus
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
    eng = engine_factory(f"sqlite+aiosqlite:///{(tmp_path / 'ks.db').as_posix()}")
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
async def test_double_activation_publishes_once_but_records_two_events(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name="t", feature_flags={}))
        await s.commit()

    bus = MessageBus()
    published: list[RiskKillSwitchActivated] = []
    sub = bus.subscribe(RiskKillSwitchActivated, lambda ev: published.append(ev))  # type: ignore[arg-type,misc]
    try:
        async with with_tenant_context(tid), sf() as session:
            session_var.set(session)
            service = RiskService(repository=RiskRepository(session), bus=bus)
            await service.activate_kill_switch(
                tenant_id=tid, source="cli", actor_user_id=None, reason="first"
            )
            await service.activate_kill_switch(
                tenant_id=tid, source="channel_command", actor_user_id=None, reason="again"
            )
            await session.commit()
            events = (await session.execute(sa.select(KillSwitchEventORM))).scalars().all()
        # drain the bus
        import asyncio

        await asyncio.sleep(0)
        await asyncio.sleep(0)
    finally:
        await bus.unsubscribe(sub)
        await bus.aclose()

    # Two audit events (every attempt captured), but exactly one publish.
    assert len([e for e in events if e.transition == "activated"]) == 2
    assert len(published) == 1


@pytest.mark.asyncio
async def test_noop_deactivate_of_never_active_publishes_nothing(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name="t", feature_flags={}))
        await s.commit()

    bus = MessageBus()
    published: list[RiskKillSwitchDeactivated] = []
    sub = bus.subscribe(RiskKillSwitchDeactivated, lambda ev: published.append(ev))  # type: ignore[arg-type,misc]
    try:
        async with with_tenant_context(tid), sf() as session:
            session_var.set(session)
            service = RiskService(repository=RiskRepository(session), bus=bus)
            await service.deactivate_kill_switch(
                tenant_id=tid, source="cli", actor_user_id=None, reason="resume"
            )
            await session.commit()
        import asyncio

        await asyncio.sleep(0)
        await asyncio.sleep(0)
    finally:
        await bus.unsubscribe(sub)
        await bus.aclose()

    # Never active → no real transition → no Deactivated event published.
    assert published == []
