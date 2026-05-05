"""``TradingService`` orchestration — propose() emits ProposalCreated;
ProposalApproved triggers the broker call exactly once under idempotent
subscribe.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from iguanatrader.contexts.trading.events import (
    ProposalApproved,
    ProposalCreated,
)
from iguanatrader.contexts.trading.ports import (
    BarHistory,
    BrokerOrderId,
    EquitySnapshotValue,
    FillEvent,
    NewOrder,
    Position,
    Proposal,
    StrategyConfigSnapshot,
)
from iguanatrader.contexts.trading.service import (
    KillSwitchActiveError,
    TradingService,
)
from iguanatrader.shared.contextvars import tenant_id_var
from iguanatrader.shared.messagebus import MessageBus


class _FakeBroker:
    def __init__(self) -> None:
        self.calls: list[NewOrder] = []

    async def place_order(self, order: NewOrder) -> BrokerOrderId:
        self.calls.append(order)
        return BrokerOrderId(f"fake-{len(self.calls)}")

    async def cancel_order(self, broker_order_id: BrokerOrderId) -> None:
        return None

    async def _empty(self) -> AsyncIterator[FillEvent]:
        if False:
            yield FillEvent(
                tenant_id=uuid4(),
                order_id=uuid4(),
                quantity_filled=Decimal("0"),
                fill_price=Decimal("0"),
                commission=Decimal("0"),
                commission_currency="USD",
                filled_at=datetime.now(),
            )

    def reconcile_fills(self, since: datetime) -> AsyncIterator[FillEvent]:
        return self._empty()

    async def get_position(self, symbol: str) -> Position:
        raise NotImplementedError

    async def get_account_equity(self) -> EquitySnapshotValue:
        raise NotImplementedError


class _FakeStrategy:
    def __init__(self, *, return_proposal: Proposal | None) -> None:
        self._proposal = return_proposal

    def name(self) -> str:
        return "fake"

    def version(self) -> str:
        return "1.0.0"

    def evaluate(
        self,
        symbol: str,
        bars: BarHistory,
        config: StrategyConfigSnapshot,
    ) -> Proposal | None:
        return self._proposal


def _make_proposal(tenant_id: UUID, strategy_config_id: UUID) -> Proposal:
    return Proposal(
        tenant_id=tenant_id,
        strategy_config_id=strategy_config_id,
        symbol="SPY",
        side="buy",
        quantity=Decimal("10"),
        entry_price_indicative=Decimal("450.25"),
        stop_price=Decimal("440.00"),
        confidence_score=Decimal("0.75"),
        reasoning={"signal": "donchian_atr"},
        mode="paper",
        correlation_id=uuid4(),
    )


def _make_config(strategy_config_id: UUID, tenant_id: UUID) -> StrategyConfigSnapshot:
    return StrategyConfigSnapshot(
        id=strategy_config_id,
        tenant_id=tenant_id,
        strategy_kind="fake",
        symbol="SPY",
        params={},
        enabled=True,
        version=1,
    )


@pytest.mark.asyncio
async def test_execute_on_approval_handler_idempotent_under_duplicate_publish() -> None:
    """Two ``ProposalApproved`` events with the same id are deduplicated.

    The bus subscription registered by ``register_subscriptions`` uses
    ``idempotent=True`` (slice 2 D1 contract). The handler's
    ``execute_on_approval`` call (skeletal in T1; T4 fills the broker
    submission) must be invoked exactly once.
    """
    bus = MessageBus()
    broker = _FakeBroker()

    tenant_id = uuid4()
    strategy_id = uuid4()

    service = TradingService(
        bus=bus,
        broker=broker,  # type: ignore[arg-type]
        strategy_resolver=lambda _sid: _FakeStrategy(return_proposal=None),
    )

    invocation_count = {"n": 0}

    async def _wrapper(event: ProposalApproved) -> None:
        invocation_count["n"] += 1
        await service.execute_on_approval_handler(event)

    bus.subscribe(ProposalApproved, _wrapper, idempotent=True)

    pid = uuid4()
    await bus.publish(
        ProposalApproved(tenant_id=tenant_id, proposal_id=pid)
    )
    await bus.publish(
        ProposalApproved(tenant_id=tenant_id, proposal_id=pid)
    )

    # Drain queues. asyncio.sleep(0) repeatedly until everything has been
    # processed; the FIFO worker hops control on each await.
    for _ in range(10):
        await asyncio.sleep(0)

    assert invocation_count["n"] == 1
    await bus.aclose()
    _ = strategy_id  # keep referenced (ruff)


@pytest.mark.asyncio
async def test_propose_emits_proposal_created_with_correct_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``propose()`` publishes ``ProposalCreated`` with the entity PK +
    canonical event_name when the strategy returns a non-None proposal.

    The ORM INSERT path is bypassed via a fake session so this test does
    not require a live SQLAlchemy engine.
    """
    bus = MessageBus()
    broker = _FakeBroker()

    tenant_id = uuid4()
    strategy_id = uuid4()
    proposal = _make_proposal(tenant_id, strategy_id)
    strategy = _FakeStrategy(return_proposal=proposal)

    service = TradingService(
        bus=bus,
        broker=broker,  # type: ignore[arg-type]
        strategy_resolver=lambda _sid: strategy,
    )

    received: list[ProposalCreated] = []

    async def _capture(event: ProposalCreated) -> None:
        received.append(event)

    bus.subscribe(ProposalCreated, _capture)

    # Inject a fake session into ``session_var`` so ``BaseRepository().session``
    # returns it — propose() persists via that path.
    class _FakeSession:
        def __init__(self) -> None:
            self.added: list[Any] = []

        def add(self, item: Any) -> None:
            self.added.append(item)

    fake = _FakeSession()
    from iguanatrader.shared.contextvars import session_var

    session_token = session_var.set(fake)
    tenant_token = tenant_id_var.set(tenant_id)
    try:
        await service.propose(
            symbol="SPY",
            strategy_config_id=strategy_id,
            bars=BarHistory(symbol="SPY", bars=[]),
            config=_make_config(strategy_id, tenant_id),
        )
    finally:
        tenant_id_var.reset(tenant_token)
        session_var.reset(session_token)

    for _ in range(10):
        await asyncio.sleep(0)

    assert len(received) == 1
    ev = received[0]
    assert ev.event_name == "trading.proposal.created"
    assert ev.tenant_id == tenant_id
    assert ev.symbol == "SPY"
    assert ev.strategy_kind == "fake"
    assert len(fake.added) == 1
    await bus.aclose()


@pytest.mark.asyncio
async def test_propose_returns_none_and_does_not_publish_on_no_signal() -> None:
    """When ``StrategyPort.evaluate`` returns ``None`` no event is
    published and no row is added.
    """
    bus = MessageBus()
    broker = _FakeBroker()

    tenant_id = uuid4()
    strategy_id = uuid4()
    strategy = _FakeStrategy(return_proposal=None)

    service = TradingService(
        bus=bus,
        broker=broker,  # type: ignore[arg-type]
        strategy_resolver=lambda _sid: strategy,
    )

    received: list[ProposalCreated] = []

    async def _capture(event: ProposalCreated) -> None:
        received.append(event)

    bus.subscribe(ProposalCreated, _capture)

    tenant_token = tenant_id_var.set(tenant_id)
    try:
        result = await service.propose(
            symbol="SPY",
            strategy_config_id=strategy_id,
            bars=BarHistory(symbol="SPY", bars=[]),
            config=_make_config(strategy_id, tenant_id),
        )
    finally:
        tenant_id_var.reset(tenant_token)

    for _ in range(5):
        await asyncio.sleep(0)

    assert result is None
    assert received == []
    await bus.aclose()


@pytest.mark.asyncio
async def test_propose_raises_when_kill_switch_active() -> None:
    bus = MessageBus()
    broker = _FakeBroker()

    tenant_id = uuid4()
    strategy_id = uuid4()
    strategy = _FakeStrategy(return_proposal=None)

    service = TradingService(
        bus=bus,
        broker=broker,  # type: ignore[arg-type]
        strategy_resolver=lambda _sid: strategy,
    )

    # Simulate a KillSwitchTripped event arriving by calling halt_handler
    # directly (T1 stub; K1 will publish the real event).
    await service.halt_handler(object())

    tenant_token = tenant_id_var.set(tenant_id)
    try:
        with pytest.raises(KillSwitchActiveError):
            await service.propose(
                symbol="SPY",
                strategy_config_id=strategy_id,
                bars=BarHistory(symbol="SPY", bars=[]),
                config=_make_config(strategy_id, tenant_id),
            )
    finally:
        tenant_id_var.reset(tenant_token)
    await bus.aclose()
