"""WS-4 ephemeral live-gateway gate in ``execute_on_approval_handler``.

A LIVE order must never be sent at a gateway we cannot confirm is up. When the
injected coordinator reports not-ready, the execute path fails closed:
``OrderRejected(reason="gateway_unavailable")``, the broker is NOT called, and no
Trade/Order row is created. A ready gateway proceeds. Paper orders never consult
the gateway at all.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.trading.events import OrderPlaced, OrderRejected, ProposalApproved
from iguanatrader.contexts.trading.models import Order, StrategyConfig, TradeProposal
from iguanatrader.contexts.trading.ports import BrokerOrderId, NewOrder
from iguanatrader.contexts.trading.service import TradingService
from iguanatrader.persistence import (
    Tenant,
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.shared.contextvars import with_session_context
from iguanatrader.shared.messagebus import MessageBus
from sqlalchemy import func, select
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
    eng = engine_factory(f"sqlite+aiosqlite:///{(tmp_path / 'ig_gw.db').as_posix()}")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def sf(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return session_factory(engine)


class _RecordingBus(MessageBus):
    def __init__(self) -> None:
        super().__init__()
        self.published: list[Any] = []

    async def publish(self, event: Any) -> None:
        self.published.append(event)


class _FakeBroker:
    def __init__(self) -> None:
        self.calls: list[NewOrder] = []

    async def place_order(self, order: NewOrder) -> BrokerOrderId:
        self.calls.append(order)
        return BrokerOrderId(f"fake-{len(self.calls)}")


class _FakeGateway:
    def __init__(self, *, ready: bool) -> None:
        self._ready = ready
        self.calls: list[str] = []

    async def ensure_up(self, *, reason: str) -> bool:
        self.calls.append(reason)
        return self._ready


async def _seed_live_proposal(
    sf: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    config_id: UUID,
    proposal_id: UUID,
    mode: str,
) -> None:
    async with sf() as s:
        s.add(Tenant(id=tenant_id, name="t-gw", feature_flags={}))
        await s.commit()
    async with sf() as s, with_session_context(s, tenant_id):
        s.add(
            StrategyConfig(
                id=config_id,
                tenant_id=tenant_id,
                strategy_kind="donchian_atr",
                symbol="SPY",
                params={"lookback": 20},
                enabled=True,
                version=1,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await s.flush()
        s.add(
            TradeProposal(
                id=proposal_id,
                tenant_id=tenant_id,
                strategy_config_id=config_id,
                symbol="SPY",
                side="buy",
                quantity=Decimal("10"),
                entry_price_indicative=Decimal("450"),
                stop_price=Decimal("440"),
                target_price=Decimal("470"),
                confidence_score=Decimal("0.7"),
                reasoning={"why": "seed"},
                mode=mode,
                correlation_id=uuid4(),
                state="pending_approval",
                created_at=datetime.now(UTC),
            )
        )
        await s.commit()


def _service(broker: _FakeBroker, bus: MessageBus, gateway: Any) -> TradingService:
    return TradingService(
        bus=bus,
        broker=broker,  # type: ignore[arg-type]
        strategy_resolver=_resolve_none,
        live_gateway=gateway,
    )


async def _resolve_none(_sid: UUID) -> Any:
    return None


async def _count_orders(session: AsyncSession) -> int:
    # Fresh per-test DB, so a total count of 0 proves the fail-closed path
    # created no Order row (Order links to the proposal via trade_id, not a
    # direct column).
    return int((await session.execute(select(func.count()).select_from(Order))).scalar() or 0)


@pytest.mark.asyncio
async def test_live_order_fails_closed_when_gateway_not_ready(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, config_id, proposal_id = uuid4(), uuid4(), uuid4()
    await _seed_live_proposal(
        sf, tenant_id=tenant_id, config_id=config_id, proposal_id=proposal_id, mode="live"
    )
    broker = _FakeBroker()
    bus = _RecordingBus()
    gateway = _FakeGateway(ready=False)
    service = _service(broker, bus, gateway)

    async with sf() as session, with_session_context(session, tenant_id):
        await service.execute_on_approval_handler(
            ProposalApproved(tenant_id=tenant_id, proposal_id=proposal_id)
        )
        # Fail-closed: gateway consulted, broker NOT called, no Order row.
        assert gateway.calls  # ensure_up was invoked
        assert broker.calls == []
        assert await _count_orders(session) == 0

    rejected = [e for e in bus.published if isinstance(e, OrderRejected)]
    assert len(rejected) == 1
    assert rejected[0].reason == "gateway_unavailable"


@pytest.mark.asyncio
async def test_live_order_proceeds_when_gateway_ready(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, config_id, proposal_id = uuid4(), uuid4(), uuid4()
    await _seed_live_proposal(
        sf, tenant_id=tenant_id, config_id=config_id, proposal_id=proposal_id, mode="live"
    )
    broker = _FakeBroker()
    bus = _RecordingBus()
    gateway = _FakeGateway(ready=True)
    service = _service(broker, bus, gateway)

    async with sf() as session, with_session_context(session, tenant_id):
        await service.execute_on_approval_handler(
            ProposalApproved(tenant_id=tenant_id, proposal_id=proposal_id)
        )
        assert gateway.calls
        assert len(broker.calls) == 1  # order placed
        assert not [e for e in bus.published if isinstance(e, OrderRejected)]
        assert [e for e in bus.published if isinstance(e, OrderPlaced)]


@pytest.mark.asyncio
async def test_paper_order_never_consults_gateway(
    sf: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, config_id, proposal_id = uuid4(), uuid4(), uuid4()
    await _seed_live_proposal(
        sf, tenant_id=tenant_id, config_id=config_id, proposal_id=proposal_id, mode="paper"
    )
    broker = _FakeBroker()
    bus = _RecordingBus()
    gateway = _FakeGateway(ready=False)  # would block IF consulted
    service = _service(broker, bus, gateway)

    async with sf() as session, with_session_context(session, tenant_id):
        await service.execute_on_approval_handler(
            ProposalApproved(tenant_id=tenant_id, proposal_id=proposal_id)
        )
        # Paper path ignores the gateway entirely and proceeds.
        assert gateway.calls == []
        assert len(broker.calls) == 1
