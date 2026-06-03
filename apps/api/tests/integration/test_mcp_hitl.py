"""MCP HITL adapter — identity revalidation, owner gate, durable halt.

Slice ``mcp-hitl-approvals`` §2/§3. Exercises the security spine of
``api/routes/mcp_hitl.py`` directly against a real tenant-scoped SQLite
engine, the canonical listeners, and the real ``command_handler.dispatch``
chain — no FastAPI client needed.

The successful approve path (which needs a real ``approval_requests`` row)
lives in ``test_mcp_hitl_approve.py``; that file seeds the real proposal so
the FK resolves. Here we import the risk ORM so the kill-switch tables exist
for the durable-halt test, and avoid inserting any ``approval_requests`` row.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID, uuid4

import iguanatrader.contexts.approval.models as _approval_models
import iguanatrader.contexts.risk.orm as _risk_orm
import pytest
from iguanatrader.api.routes.mcp import MCPActionFailedError, MCPForbiddenError
from iguanatrader.api.routes.mcp_hitl import _run_action
from iguanatrader.contexts.risk.repository import RiskRepository
from iguanatrader.persistence import (
    AuthorizedSender,
    Tenant,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.shared.contextvars import with_tenant_context
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

_REGISTERED = (_approval_models, _risk_orm)

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(autouse=True)
def _listeners() -> Iterator[None]:
    register_global_listeners()
    try:
        yield
    finally:
        unregister_global_listeners()


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    eng = engine_factory(f"sqlite+aiosqlite:///{(tmp_path / 'ig_mcp_hitl.db').as_posix()}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def sf(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return session_factory(engine)


async def _seed_tenant(sf: async_sessionmaker[AsyncSession]) -> UUID:
    tid = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name=f"tenant-{tid.hex[:8]}", feature_flags={}))
        await s.commit()
    return tid


async def _add_sender(
    sf: async_sessionmaker[AsyncSession],
    tid: UUID,
    *,
    external_id: str,
    role: str,
    enabled: bool = True,
) -> None:
    async with with_tenant_context(tid), sf() as s:
        s.add(
            AuthorizedSender(
                id=uuid4(),
                tenant_id=tid,
                channel="telegram",
                external_id=external_id,
                display_name=None,
                enabled=enabled,
                role=role,
            )
        )
        await s.commit()


# ---------------------------------------------------------------------------
# Layer 2 — identity revalidation against AuthorizedSender
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_sender_denied(sf: async_sessionmaker[AsyncSession]) -> None:
    tid = await _seed_tenant(sf)
    async with with_tenant_context(tid), sf() as db:
        with pytest.raises(MCPForbiddenError):
            await _run_action(
                db,
                command_name="/approve",
                channel="telegram",
                external_id="nobody",
                request_id=uuid4(),
            )


@pytest.mark.asyncio
async def test_disabled_sender_denied(sf: async_sessionmaker[AsyncSession]) -> None:
    tid = await _seed_tenant(sf)
    await _add_sender(sf, tid, external_id="owner-1", role="owner", enabled=False)
    async with with_tenant_context(tid), sf() as db:
        with pytest.raises(MCPForbiddenError):
            await _run_action(
                db,
                command_name="/approve",
                channel="telegram",
                external_id="owner-1",
                request_id=uuid4(),
            )


# ---------------------------------------------------------------------------
# Owner gate (Gate E: owner siempre)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_owner_denied_on_approve(sf: async_sessionmaker[AsyncSession]) -> None:
    tid = await _seed_tenant(sf)
    await _add_sender(sf, tid, external_id="plain-user", role="user")
    async with with_tenant_context(tid), sf() as db:
        with pytest.raises(MCPForbiddenError):
            await _run_action(
                db,
                command_name="/approve",
                channel="telegram",
                external_id="plain-user",
                request_id=uuid4(),
            )


@pytest.mark.asyncio
async def test_non_owner_denied_on_halt(sf: async_sessionmaker[AsyncSession]) -> None:
    tid = await _seed_tenant(sf)
    await _add_sender(sf, tid, external_id="plain-user", role="user")
    async with with_tenant_context(tid), sf() as db:
        with pytest.raises(MCPForbiddenError):
            await _run_action(
                db,
                command_name="/halt",
                channel="telegram",
                external_id="plain-user",
            )


# ---------------------------------------------------------------------------
# Owner kill-switch — durable (#27)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_owner_halt_activates_durable_kill_switch(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid = await _seed_tenant(sf)
    await _add_sender(sf, tid, external_id="owner-1", role="owner")

    async with with_tenant_context(tid), sf() as db:
        resp = await _run_action(
            db,
            command_name="/halt",
            channel="telegram",
            external_id="owner-1",
            raw_args="market looks wrong",
        )
    assert resp.status == "ok"

    # Durable (#27): a FRESH session reads the kill-switch as active —
    # record_halt committed the event + cache at activation time.
    async with with_tenant_context(tid), sf() as check:
        active = await RiskRepository(check).load_kill_switch_state(tid)
    assert active is True


@pytest.mark.asyncio
async def test_owner_approve_missing_request_is_action_failed(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    """Gate passed (owner) → dispatch ran → ApprovalNotFound surfaces as 422,
    distinguishing it from the 403 a non-owner gets before dispatch."""
    tid = await _seed_tenant(sf)
    await _add_sender(sf, tid, external_id="owner-1", role="owner")
    async with with_tenant_context(tid), sf() as db:
        with pytest.raises(MCPActionFailedError):
            await _run_action(
                db,
                command_name="/approve",
                channel="telegram",
                external_id="owner-1",
                request_id=uuid4(),
            )
