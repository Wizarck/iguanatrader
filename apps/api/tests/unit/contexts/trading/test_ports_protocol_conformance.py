"""``BrokerPort`` + ``StrategyPort`` PEP 544 structural-typing checks.

A class with the matching method signatures satisfies the protocol via
:func:`isinstance` (``@runtime_checkable`` is inherited from
:class:`iguanatrader.shared.ports.Port`). A class missing a method
fails the runtime check; the static-typing equivalent is enforced by
``mypy --strict`` in CI.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from iguanatrader.contexts.trading.ports import (
    BarHistory,
    BrokerOrderId,
    BrokerPort,
    EquitySnapshotValue,
    FillEvent,
    NewOrder,
    Position,
    Proposal,
    StrategyConfigSnapshot,
    StrategyPort,
    WorkingOrder,
)


# ----------------------------------------------------------------------
# Stub broker — matches the BrokerPort signatures.
# ----------------------------------------------------------------------
class _StubBroker:
    async def place_order(self, order: NewOrder) -> BrokerOrderId:
        return BrokerOrderId(f"stub-{order.symbol}")

    async def cancel_order(self, broker_order_id: BrokerOrderId) -> None:
        return None

    async def _empty(self) -> AsyncIterator[FillEvent]:  # pragma: no cover
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
        return Position(
            tenant_id=uuid4(),
            symbol=symbol,
            quantity=Decimal("0"),
            average_price=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            currency="USD",
        )

    async def list_positions(self) -> list[Position]:
        return []

    async def get_account_equity(self) -> EquitySnapshotValue:
        return EquitySnapshotValue(
            tenant_id=uuid4(),
            mode="paper",
            account_equity=Decimal("0"),
            cash_balance=Decimal("0"),
            realized_pnl_today=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            currency="USD",
            snapshot_kind="event",
            captured_at=datetime.now(),
        )

    async def list_working_orders(self) -> list[WorkingOrder]:
        return []


class _BrokenBroker:
    async def place_order(self, order: NewOrder) -> BrokerOrderId:
        return BrokerOrderId("broken")

    # Missing: cancel_order, reconcile_fills, get_position, get_account_equity.


def test_stub_broker_satisfies_broker_port_runtime() -> None:
    assert isinstance(_StubBroker(), BrokerPort)


def test_broken_broker_fails_broker_port_runtime() -> None:
    assert not isinstance(_BrokenBroker(), BrokerPort)


# ----------------------------------------------------------------------
# Stub strategy — matches the StrategyPort signatures.
# ----------------------------------------------------------------------
class _StubStrategy:
    def name(self) -> str:
        return "stub"

    def version(self) -> str:
        return "1.0.0"

    def evaluate(
        self,
        symbol: str,
        bars: BarHistory,
        config: StrategyConfigSnapshot,
    ) -> Proposal | None:
        return None


class _BrokenStrategy:
    def name(self) -> str:
        return "broken"

    # Missing: version + evaluate.


def test_stub_strategy_satisfies_strategy_port_runtime() -> None:
    assert isinstance(_StubStrategy(), StrategyPort)


def test_broken_strategy_fails_strategy_port_runtime() -> None:
    assert not isinstance(_BrokenStrategy(), StrategyPort)


def test_unused_imports_kept_alive() -> None:
    """Ensure the imported types remain referenced for ruff."""
    assert UUID is not None
