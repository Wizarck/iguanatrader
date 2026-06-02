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
    ApprovalRequested,
    ProposalApproved,
    ProposalCreated,
    ProposalRejected,
    ProposalRiskEvaluated,
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


def _async_const(strategy: Any) -> Any:
    """Slice T4-followup-market-data: ``StrategyResolver`` is now async.

    Helper to wrap a fixed strategy as an async resolver so existing
    tests don't need a ``async def`` per call site.
    """

    async def _resolve(_sid: UUID) -> Any:
        return strategy

    return _resolve


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

    async def list_positions(self) -> list[Position]:
        return []

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
async def test_risk_check_handler_clip_outcome_fails_safe() -> None:
    """#37: a ``clip`` risk outcome must NOT flow to approval (which would
    execute at full size, ignoring clip_quantity). Until clip is threaded
    end-to-end the handler fails safe by publishing ProposalRejected."""

    class _RecordingBus(MessageBus):
        def __init__(self) -> None:
            super().__init__()
            self.published: list[Any] = []

        async def publish(self, event: Any) -> None:
            self.published.append(event)
            await super().publish(event)

    bus = _RecordingBus()
    service = TradingService(
        bus=bus,
        broker=_FakeBroker(),
        strategy_resolver=_async_const(None),
    )
    tenant_id = uuid4()
    proposal_id = uuid4()
    await service.risk_check_handler(
        ProposalRiskEvaluated(
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            outcome="clip",
            clip_quantity=Decimal("5"),
        )
    )

    rejected = [e for e in bus.published if isinstance(e, ProposalRejected)]
    approvals = [e for e in bus.published if isinstance(e, ApprovalRequested)]
    assert len(approvals) == 0  # clip never reaches approval
    assert len(rejected) == 1
    assert rejected[0].reason == "risk_engine_clip_unsupported"
    await bus.aclose()


@pytest.mark.asyncio
async def test_bus_dedups_duplicate_proposal_approved_once_processed() -> None:
    """An idempotent subscription drops a duplicate ``ProposalApproved``
    once the first delivery has COMPLETED.

    The bus records an ``idempotency_key`` only after the handler returns
    cleanly (``_worker``), so duplicates issued *within the same burst*
    (before the first handler returns) are NOT deduped at the bus layer.
    The execute handler's own DB idempotency check
    (``OrderRepository.get_by_proposal_id``) is the second line of
    defence for the burst case and is exercised by the integration tests
    (a real session + committed order row is required to show it).

    This test pins the bus-level contract: publish, let the first
    delivery finish (key recorded), then a same-key publish is dropped.
    """
    bus = MessageBus()
    invocation_count = {"n": 0}

    async def _handler(event: ProposalApproved) -> None:
        invocation_count["n"] += 1

    bus.subscribe(ProposalApproved, _handler, idempotent=True)

    pid = uuid4()
    tenant_id = uuid4()
    await bus.publish(ProposalApproved(tenant_id=tenant_id, proposal_id=pid))
    # Let the first delivery complete so its idempotency_key is recorded.
    for _ in range(10):
        await asyncio.sleep(0)
    await bus.publish(ProposalApproved(tenant_id=tenant_id, proposal_id=pid))
    for _ in range(10):
        await asyncio.sleep(0)

    assert invocation_count["n"] == 1
    await bus.aclose()


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
        broker=broker,
        strategy_resolver=_async_const(strategy),
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
        broker=broker,
        strategy_resolver=_async_const(strategy),
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
        broker=broker,
        strategy_resolver=_async_const(strategy),
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
