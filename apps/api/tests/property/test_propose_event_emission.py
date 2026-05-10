"""Hypothesis property test for ``TradingService.propose`` emission contract.

Slice propose-event-emission-property. For every random strategy
result (Proposal | None):

* Strategy returns Proposal -> exactly 1 ``ProposalCreated`` event
  published on the bus.
* Strategy returns None -> zero events.
* KillSwitchActiveError raised mid-flight (before evaluate runs) ->
  zero events (defensive; bus untouched on early-raise).

This is the regression net for the K1+P1+T4 bus-driven pipeline:
the rest of the chain assumes ``propose`` is 1:1 with its emission.

Markers: ``@pytest.mark.property``. NOT ``ci_blocking`` because the
emission contract is already covered by unit tests; this property
is the regression net catching edge cases on random Proposal shapes.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from iguanatrader.contexts.trading.events import ProposalCreated
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
    async def place_order(self, order: NewOrder) -> BrokerOrderId:
        return BrokerOrderId("fake")

    async def cancel_order(self, broker_order_id: BrokerOrderId) -> None:
        return None

    def reconcile_fills(self, since: datetime) -> AsyncIterator[FillEvent]:
        async def _empty() -> AsyncIterator[FillEvent]:
            if False:
                yield FillEvent(
                    tenant_id=uuid4(),
                    order_id=uuid4(),
                    quantity_filled=Decimal("0"),
                    fill_price=Decimal("0"),
                    commission=Decimal("0"),
                    commission_currency="USD",
                    filled_at=datetime.now(UTC),
                )

        return _empty()

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


def _build_proposal(
    *,
    tenant_id: UUID,
    strategy_config_id: UUID,
    side: str,
    quantity_raw: float,
    entry_raw: float,
    stop_offset: float,
) -> Proposal:
    quantity = Decimal(str(round(max(quantity_raw, 0.01), 4)))
    entry = Decimal(str(round(max(entry_raw, 1.0), 4)))
    if side == "buy":
        stop = entry - Decimal(str(round(max(stop_offset, 0.01), 4)))
        if stop <= Decimal("0"):
            stop = entry / Decimal("2")
    else:
        stop = entry + Decimal(str(round(max(stop_offset, 0.01), 4)))
    return Proposal(
        tenant_id=tenant_id,
        strategy_config_id=strategy_config_id,
        symbol="SPY",
        side=side,
        quantity=quantity,
        entry_price_indicative=entry,
        stop_price=stop,
        confidence_score=Decimal("0.5"),
        reasoning={"hypothesis": "test"},
        mode="paper",
        correlation_id=uuid4(),
    )


async def _drain(*, ticks: int = 5) -> None:
    for _ in range(ticks):
        await asyncio.sleep(0)


@pytest.mark.property
@given(
    return_proposal=st.booleans(),
    side=st.sampled_from(["buy", "sell"]),
    quantity=st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False),
    entry=st.floats(min_value=1.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
    stop_offset=st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False),
)
@settings(
    deadline=None,
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_propose_emits_one_event_iff_strategy_returns_proposal(
    return_proposal: bool,
    side: str,
    quantity: float,
    entry: float,
    stop_offset: float,
) -> None:
    """Random Proposal | None -> bus emission count matches."""

    async def _run() -> None:
        tenant_id = uuid4()
        strategy_config_id = uuid4()

        proposal: Proposal | None = None
        if return_proposal:
            proposal = _build_proposal(
                tenant_id=tenant_id,
                strategy_config_id=strategy_config_id,
                side=side,
                quantity_raw=quantity,
                entry_raw=entry,
                stop_offset=stop_offset,
            )

        captured: list[ProposalCreated] = []

        async def _capture(evt: ProposalCreated) -> None:
            captured.append(evt)

        bus = MessageBus()
        bus.subscribe(ProposalCreated, _capture)
        broker = _FakeBroker()
        strategy = _FakeStrategy(return_proposal=proposal)

        async def _resolve(_sid: UUID) -> _FakeStrategy:
            return strategy

        service = TradingService(
            bus=bus,
            broker=broker,  # type: ignore[arg-type]
            strategy_resolver=_resolve,  # type: ignore[arg-type]
        )

        token = tenant_id_var.set(tenant_id)
        try:
            config = StrategyConfigSnapshot(
                id=strategy_config_id,
                tenant_id=tenant_id,
                strategy_kind="fake",
                symbol="SPY",
                params={},
                enabled=True,
                version=1,
            )
            await service.propose(
                symbol="SPY",
                strategy_config_id=strategy_config_id,
                bars=BarHistory(symbol="SPY", bars=()),
                config=config,
            )
            await _drain()
        finally:
            tenant_id_var.reset(token)
            await bus.aclose()

        expected = 1 if return_proposal else 0
        assert len(captured) == expected, (
            f"Expected {expected} ProposalCreated events, got {len(captured)} "
            f"(return_proposal={return_proposal}, side={side}, quantity={quantity})"
        )

    asyncio.run(_run())


@pytest.mark.property
@given(
    return_proposal=st.booleans(),
)
@settings(
    deadline=None,
    max_examples=20,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
def test_kill_switch_active_emits_zero_events_regardless_of_strategy_output(
    return_proposal: bool,
) -> None:
    """When kill_switch is active, propose raises before evaluate; bus untouched."""

    async def _run() -> None:
        tenant_id = uuid4()
        strategy_config_id = uuid4()
        proposal: Proposal | None = None
        if return_proposal:
            proposal = _build_proposal(
                tenant_id=tenant_id,
                strategy_config_id=strategy_config_id,
                side="buy",
                quantity_raw=10.0,
                entry_raw=100.0,
                stop_offset=5.0,
            )

        captured: list[ProposalCreated] = []

        async def _capture(evt: ProposalCreated) -> None:
            captured.append(evt)

        bus = MessageBus()
        bus.subscribe(ProposalCreated, _capture)
        strategy = _FakeStrategy(return_proposal=proposal)

        async def _resolve(_sid: UUID) -> _FakeStrategy:
            return strategy

        service = TradingService(
            bus=bus,
            broker=_FakeBroker(),  # type: ignore[arg-type]
            strategy_resolver=_resolve,  # type: ignore[arg-type]
        )
        service._kill_switch_active = True  # flip after construction

        token = tenant_id_var.set(tenant_id)
        try:
            config = StrategyConfigSnapshot(
                id=strategy_config_id,
                tenant_id=tenant_id,
                strategy_kind="fake",
                symbol="SPY",
                params={},
                enabled=True,
                version=1,
            )
            with pytest.raises(KillSwitchActiveError):
                await service.propose(
                    symbol="SPY",
                    strategy_config_id=strategy_config_id,
                    bars=BarHistory(symbol="SPY", bars=()),
                    config=config,
                )
            await _drain()
        finally:
            tenant_id_var.reset(token)
            await bus.aclose()

        assert captured == [], f"Kill-switch path must NOT publish events; got {len(captured)}"

    asyncio.run(_run())
