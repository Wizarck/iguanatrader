"""Position-review reconcile — slice ``position-review-broker-visibility``.

Covers the pure :func:`reconcile_positions` (intended-vs-resting matching +
divergence detection) and the :class:`PositionReviewService` wiring (DB
enumeration + broker reads → reconcile) against a fake session + fake broker.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.risk.position_review import (
    OpenTradeLevels,
    PositionReviewService,
    reconcile_positions,
)
from iguanatrader.contexts.trading.ports import Position, WorkingOrder

_TENANT = uuid4()


def _trade(
    *,
    symbol: str = "AAPL",
    side: str = "buy",
    quantity: Decimal = Decimal("10"),
    stop: Decimal = Decimal("180"),
    target: Decimal | None = Decimal("220"),
    trade_id: UUID | None = None,
) -> OpenTradeLevels:
    return OpenTradeLevels(
        trade_id=trade_id or uuid4(),
        tenant_id=_TENANT,
        symbol=symbol,
        side=side,
        quantity=quantity,
        intended_stop=stop,
        intended_target=target,
    )


def _pos(
    *, symbol: str = "AAPL", quantity: Decimal = Decimal("10"), avg: Decimal = Decimal("200")
) -> Position:
    return Position(
        tenant_id=_TENANT,
        symbol=symbol,
        quantity=quantity,
        average_price=avg,
        unrealized_pnl=Decimal("0"),
        currency="USD",
    )


def _wo(
    *,
    symbol: str = "AAPL",
    action: str = "SELL",
    order_type: str = "STP",
    limit_price: Decimal | None = None,
    stop_price: Decimal | None = None,
    status: str = "Submitted",
) -> WorkingOrder:
    return WorkingOrder(
        tenant_id=_TENANT,
        symbol=symbol,
        action=action,
        quantity=Decimal("10"),
        order_type=order_type,
        limit_price=limit_price,
        stop_price=stop_price,
        order_ref=None,
        status=status,
    )


# ----------------------------------------------------------------------
# Pure reconcile
# ----------------------------------------------------------------------


def test_clean_long_position_has_no_divergences() -> None:
    trade = _trade(stop=Decimal("180"), target=Decimal("220"))
    reviews = reconcile_positions(
        open_trades=[trade],
        broker_positions=[_pos(quantity=Decimal("10"))],
        working_orders=[
            _wo(action="SELL", order_type="STP", stop_price=Decimal("180")),
            _wo(action="SELL", order_type="LMT", limit_price=Decimal("220")),
        ],
    )
    assert len(reviews) == 1
    r = reviews[0]
    assert r.side == "long"
    assert not r.divergences
    assert r.resting_stop is not None and r.resting_stop.level == Decimal("180")
    assert r.resting_target is not None and r.resting_target.level == Decimal("220")


def test_missing_stop_at_broker_flagged() -> None:
    reviews = reconcile_positions(
        open_trades=[_trade(target=None)],
        broker_positions=[_pos()],
        working_orders=[],  # nothing resting
    )
    assert "stop_missing_at_broker" in reviews[0].divergences


def test_missing_target_flagged_when_intended() -> None:
    reviews = reconcile_positions(
        open_trades=[_trade(stop=Decimal("180"), target=Decimal("220"))],
        broker_positions=[_pos()],
        working_orders=[_wo(order_type="STP", stop_price=Decimal("180"))],
    )
    assert "target_missing_at_broker" in reviews[0].divergences
    assert "stop_missing_at_broker" not in reviews[0].divergences


def test_no_target_intended_no_target_divergence() -> None:
    reviews = reconcile_positions(
        open_trades=[_trade(target=None)],
        broker_positions=[_pos()],
        working_orders=[_wo(order_type="STP", stop_price=Decimal("180"))],
    )
    assert reviews[0].divergences == []


def test_stop_level_mismatch_flagged() -> None:
    reviews = reconcile_positions(
        open_trades=[_trade(stop=Decimal("180"), target=None)],
        broker_positions=[_pos()],
        working_orders=[_wo(order_type="STP", stop_price=Decimal("170"))],  # 5.5% off
    )
    assert "stop_level_mismatch" in reviews[0].divergences


def test_stop_within_tolerance_is_not_a_mismatch() -> None:
    # 180.00 intended vs 180.50 resting → 0.28% < 0.5% tolerance.
    reviews = reconcile_positions(
        open_trades=[_trade(stop=Decimal("180"), target=None)],
        broker_positions=[_pos()],
        working_orders=[_wo(order_type="STP", stop_price=Decimal("180.50"))],
    )
    assert reviews[0].divergences == []


def test_no_broker_position_is_orphan_divergence() -> None:
    reviews = reconcile_positions(
        open_trades=[_trade()],
        broker_positions=[],  # broker holds nothing
        working_orders=[],
    )
    assert "no_broker_position" in reviews[0].divergences
    assert reviews[0].broker_quantity is None


def test_position_size_mismatch_flagged() -> None:
    reviews = reconcile_positions(
        open_trades=[_trade(quantity=Decimal("10"), target=None)],
        broker_positions=[_pos(quantity=Decimal("7"))],
        working_orders=[_wo(order_type="STP", stop_price=Decimal("180"))],
    )
    assert "position_size_mismatch" in reviews[0].divergences


def test_short_position_matches_buy_side_protective_orders() -> None:
    # Short: exit action is BUY. A BUY STP is the protective stop.
    reviews = reconcile_positions(
        open_trades=[_trade(side="sell", stop=Decimal("220"), target=Decimal("180"))],
        broker_positions=[_pos(quantity=Decimal("-10"))],
        working_orders=[
            _wo(action="BUY", order_type="STP", stop_price=Decimal("220")),
            _wo(action="BUY", order_type="LMT", limit_price=Decimal("180")),
        ],
    )
    r = reviews[0]
    assert r.side == "short"
    assert r.divergences == []
    # abs() of the signed broker qty is compared to the DB size.
    assert r.broker_quantity == Decimal("-10")


def test_short_ignores_sell_side_orders() -> None:
    # A SELL STP is NOT a protective order for a short (it would add to it).
    reviews = reconcile_positions(
        open_trades=[_trade(side="sell", stop=Decimal("220"), target=None)],
        broker_positions=[_pos(quantity=Decimal("-10"))],
        working_orders=[_wo(action="SELL", order_type="STP", stop_price=Decimal("220"))],
    )
    assert "stop_missing_at_broker" in reviews[0].divergences


def test_two_open_trades_same_symbol_is_ambiguous() -> None:
    reviews = reconcile_positions(
        open_trades=[_trade(symbol="AAPL"), _trade(symbol="AAPL")],
        broker_positions=[_pos()],
        working_orders=[_wo(order_type="STP", stop_price=Decimal("180"))],
    )
    assert len(reviews) == 2
    for r in reviews:
        assert "ambiguous_multiple_open_trades_same_symbol" in r.divergences
        # No legs attributed under ambiguity.
        assert r.resting_stop is None and r.resting_target is None


# ----------------------------------------------------------------------
# Service wiring (fake session + fake broker)
# ----------------------------------------------------------------------


class _FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    async def execute(self, _stmt: Any) -> _FakeResult:
        return _FakeResult(self._rows)


class _FakeBroker:
    def __init__(self, positions: list[Position], working: list[WorkingOrder]) -> None:
        self._positions = positions
        self._working = working

    async def list_positions(self) -> list[Position]:
        return self._positions

    async def list_working_orders(self) -> list[WorkingOrder]:
        return self._working


@pytest.mark.asyncio
async def test_service_review_wires_db_and_broker() -> None:
    trade_id = uuid4()
    rows = [
        (trade_id, _TENANT, "AAPL", "buy", Decimal("10"), Decimal("180"), Decimal("220")),
    ]
    service = PositionReviewService(
        broker=_FakeBroker(  # type: ignore[arg-type]
            positions=[_pos(quantity=Decimal("10"))],
            working=[_wo(order_type="STP", stop_price=Decimal("180"))],  # target missing
        ),
        session=_FakeSession(rows),  # type: ignore[arg-type]
        trailing_audit_repo=None,
    )
    result = await service.review()
    assert result.broker_positions_read == 1
    assert result.broker_working_orders_read == 1
    assert len(result.reviews) == 1
    assert result.reviews[0].trade_id == trade_id
    assert "target_missing_at_broker" in result.reviews[0].divergences
    assert result.divergences_detected == 1
