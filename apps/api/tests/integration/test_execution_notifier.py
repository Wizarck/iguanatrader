"""ExecutionNotifier — OrderFilled + TradeClosed operator pushes.

Slice ``mcp-hitl-approvals`` §6. Drives the two lifecycle handlers against
a fake transport and real tenant-scoped ``authorized_senders`` rows, and
asserts the right message reaches every enabled sender.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

# Side-effect import: registers trade_proposals so the approval_requests FK
# (pulled in transitively via ApprovalRepository) resolves at create_all.
import iguanatrader.contexts.trading.models as _trading_models
import pytest
from iguanatrader.contexts.approval.execution_notifier import ExecutionNotifier
from iguanatrader.contexts.trading.events import OrderFilled, TradeClosed
from iguanatrader.persistence import (
    AuthorizedSender,
    Tenant,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.shared.contextvars import session_var, with_tenant_context
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

_REGISTERED = (_trading_models,)

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class _FakeTransport:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(
        self, *, address: str, body: str, actions: tuple[tuple[str, str], ...] = ()
    ) -> str:
        self.sent.append((address, body))
        return f"wire-{len(self.sent)}"


@pytest.fixture(autouse=True)
def _listeners() -> Iterator[None]:
    register_global_listeners()
    try:
        yield
    finally:
        unregister_global_listeners()


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    eng = engine_factory(f"sqlite+aiosqlite:///{(tmp_path / 'ig_exec_notify.db').as_posix()}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def sf(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return session_factory(engine)


async def _seed_two_senders(sf: async_sessionmaker[AsyncSession]) -> UUID:
    tid = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name=f"t{tid.hex[:8]}", feature_flags={}))
        await s.commit()
    async with with_tenant_context(tid), sf() as s:
        s.add(
            AuthorizedSender(
                id=uuid4(),
                tenant_id=tid,
                channel="telegram",
                external_id="tg-1",
                display_name=None,
                enabled=True,
                role="owner",
            )
        )
        s.add(
            AuthorizedSender(
                id=uuid4(),
                tenant_id=tid,
                channel="whatsapp",
                external_id="+34999",
                display_name=None,
                enabled=True,
                role="owner",
            )
        )
        await s.commit()
    return tid


@pytest.mark.asyncio
async def test_trade_closed_pushes_pnl_to_all_senders(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid = await _seed_two_senders(sf)
    transport = _FakeTransport()
    notifier = ExecutionNotifier(transport=transport)

    event = TradeClosed(
        tenant_id=tid,
        trade_id=uuid4(),
        symbol="NVDA",
        side="buy",
        quantity=Decimal("100"),
        realised_pnl=Decimal("340.50"),
        exit_reason="target",
        closed_at=datetime.now(UTC),
    )
    async with with_tenant_context(tid), sf() as session:
        session_var.set(session)
        await notifier.on_trade_closed(event)

    assert len(transport.sent) == 2
    addresses = sorted(a for a, _ in transport.sent)
    assert addresses == ["+34999", "tg-1"]
    for _, body in transport.sent:
        assert "NVDA" in body
        assert "340.50" in body
        assert "closed" in body


@pytest.mark.asyncio
async def test_order_filled_pushes_execution_confirmation(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tid = await _seed_two_senders(sf)
    transport = _FakeTransport()
    notifier = ExecutionNotifier(transport=transport)

    event = OrderFilled(tenant_id=tid, order_id=uuid4(), fill_id=uuid4())
    async with with_tenant_context(tid), sf() as session:
        session_var.set(session)
        await notifier.on_order_filled(event)

    assert len(transport.sent) == 2
    for _, body in transport.sent:
        assert "executed" in body.lower()


@pytest.mark.asyncio
async def test_no_senders_is_noop(sf: async_sessionmaker[AsyncSession]) -> None:
    tid = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name="empty", feature_flags={}))
        await s.commit()
    transport = _FakeTransport()
    notifier = ExecutionNotifier(transport=transport)

    event = OrderFilled(tenant_id=tid, order_id=uuid4(), fill_id=uuid4())
    async with with_tenant_context(tid), sf() as session:
        session_var.set(session)
        await notifier.on_order_filled(event)  # MUST NOT raise

    assert transport.sent == []
