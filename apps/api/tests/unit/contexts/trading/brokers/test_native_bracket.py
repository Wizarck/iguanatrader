"""Tests for audit #6 — native IBKR bracket/OCO orders (feature-flagged).

Mirrors ``test_ibkr_adapter_lifecycle.py``: injects :class:`FakeIBClient`
via ``client_factory`` and drives :class:`IBKRAdapter`. Asserts the
flag-ON bracket path records a parent + protective children, and that the
flag-OFF / no-stop paths stay on the unchanged single-order path.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.trading.brokers.ibkr_adapter import IBKRAdapter
from iguanatrader.contexts.trading.brokers.ibkr_brokerage_model import IBKRBrokerageModel
from iguanatrader.contexts.trading.ports import NewOrder, derive_client_order_id

from tests._fakes.ib_async_fake import FakeIBClient


def _new_order(**overrides: object) -> NewOrder:
    base: dict[str, object] = {
        "tenant_id": uuid4(),
        "trade_id": uuid4(),
        "symbol": "AAPL",
        "side": "buy",
        "quantity": Decimal("10"),
        "order_type": "MKT",
        "client_order_id": uuid4(),
    }
    base.update(overrides)
    return NewOrder(**base)  # type: ignore[arg-type]


def _make_adapter(*, native_bracket: bool) -> tuple[IBKRAdapter, FakeIBClient]:
    fake = FakeIBClient()
    fake.configure_account_equity()
    adapter = IBKRAdapter(
        brokerage=IBKRBrokerageModel.for_paper(),
        client_factory=lambda: fake,
        native_bracket=native_bracket,
    )
    return adapter, fake


@pytest.mark.asyncio
async def test_buy_bracket_with_stop_and_target() -> None:
    adapter, fake = _make_adapter(native_bracket=True)
    await adapter.connect()
    try:
        order = _new_order(
            side="buy",
            stop_price=Decimal("95"),
            target_price=Decimal("110"),
        )
        broker_order_id = await adapter.place_order(order)

        assert len(fake.placed_brackets) == 1
        assert len(fake.placed_orders) == 0
        _contract, parent, stop_loss, take_profit = fake.placed_brackets[0]

        assert parent.action == "BUY"
        assert parent.order_type == "MKT"

        assert stop_loss.action == "SELL"
        assert stop_loss.order_type == "STP"
        assert stop_loss.aux_price == Decimal("95")

        assert take_profit is not None
        assert take_profit.action == "SELL"
        assert take_profit.order_type == "LMT"
        assert take_profit.limit_price == Decimal("110")

        # place_order returned the parent perm_id.
        assert str(broker_order_id) == "1000"
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_sell_bracket_children_are_buy() -> None:
    adapter, fake = _make_adapter(native_bracket=True)
    await adapter.connect()
    try:
        order = _new_order(
            side="sell",
            stop_price=Decimal("105"),
            target_price=Decimal("90"),
        )
        await adapter.place_order(order)

        _contract, parent, stop_loss, take_profit = fake.placed_brackets[0]
        assert parent.action == "SELL"
        assert stop_loss.action == "BUY"
        assert take_profit is not None
        assert take_profit.action == "BUY"
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_bracket_stop_only_no_target() -> None:
    adapter, fake = _make_adapter(native_bracket=True)
    await adapter.connect()
    try:
        order = _new_order(stop_price=Decimal("95"), target_price=None)
        await adapter.place_order(order)

        assert len(fake.placed_brackets) == 1
        _contract, _parent, stop_loss, take_profit = fake.placed_brackets[0]
        assert stop_loss.order_type == "STP"
        assert take_profit is None
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_native_bracket_on_but_no_stop_falls_back_to_single() -> None:
    adapter, fake = _make_adapter(native_bracket=True)
    await adapter.connect()
    try:
        order = _new_order(stop_price=None, target_price=Decimal("110"))
        await adapter.place_order(order)

        assert len(fake.placed_brackets) == 0
        assert len(fake.placed_orders) == 1
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_native_bracket_off_with_stop_uses_single_path() -> None:
    """Flag OFF (default): a stop_price does NOT trigger a bracket —
    proves the OFF path is unchanged (naked order + cron sweep)."""
    adapter, fake = _make_adapter(native_bracket=False)
    await adapter.connect()
    try:
        order = _new_order(stop_price=Decimal("95"), target_price=Decimal("110"))
        await adapter.place_order(order)

        assert len(fake.placed_brackets) == 0
        assert len(fake.placed_orders) == 1
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_bracket_child_order_refs_are_resolvable_exit_ids() -> None:
    """Regression for the dropped-exit-fill bug: each child leg carries a
    DETERMINISTIC UUID ``client_order_id`` as its ``order_ref`` (not a
    ``<entry>:stop`` suffix), so IBKR's echoed execution ``order_ref`` parses
    straight back — via ``_order_id_from_ref`` — to the exit order the service
    persisted under the SAME id. The old suffix scheme failed ``UUID(...)`` →
    zero id → the close-flow silently dropped the exit fill (``order_missing``).
    """
    adapter, fake = _make_adapter(native_bracket=True)
    await adapter.connect()
    try:
        tenant_id = uuid4()
        entry_cid = uuid4()
        order = _new_order(
            tenant_id=tenant_id,
            client_order_id=entry_cid,
            stop_price=Decimal("95"),
            target_price=Decimal("110"),
        )
        await adapter.place_order(order)

        _contract, _parent, stop_loss, take_profit = fake.placed_brackets[0]
        expected_stop = derive_client_order_id(tenant_id, "bracket_stop", entry_cid)
        expected_tp = derive_client_order_id(tenant_id, "bracket_tp", entry_cid)

        # The order_ref is the bare derived UUID (no suffix).
        assert stop_loss.order_ref == str(expected_stop)
        assert take_profit is not None
        assert take_profit.order_ref == str(expected_tp)

        # ...and it round-trips back to a non-zero exit id the reconciler can
        # match (the old suffix would have collapsed to UUID(int=0)).
        assert adapter._order_id_from_ref(stop_loss.order_ref) == expected_stop
        assert adapter._order_id_from_ref(take_profit.order_ref) == expected_tp
        assert expected_stop != UUID(int=0)
        assert expected_stop != expected_tp
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_bracket_idempotent_on_repeat_client_order_id() -> None:
    adapter, fake = _make_adapter(native_bracket=True)
    await adapter.connect()
    try:
        order = _new_order(stop_price=Decimal("95"), target_price=Decimal("110"))
        first = await adapter.place_order(order)
        second = await adapter.place_order(order)

        assert first == second
        assert len(fake.placed_brackets) == 1  # only one broker submission
    finally:
        await adapter.disconnect()
