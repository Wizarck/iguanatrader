"""Tests for :class:`IBKRAdapter` lifecycle (slice T2 design D2 + D6)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from iguanatrader.contexts.trading.brokers.ibkr_adapter import (
    BrokerWindowExhaustedError,
    IBKRAdapter,
)
from iguanatrader.contexts.trading.brokers.ibkr_brokerage_model import (
    IBKRBrokerageModel,
    UnsupportedOrderTypeError,
)
from iguanatrader.contexts.trading.ports import NewOrder
from iguanatrader.shared.heartbeat import ConnectionState

from tests._fakes.ib_async_fake import FakeIBClient


def _new_order(**overrides: object) -> NewOrder:
    base: dict[str, object] = {
        "tenant_id": uuid4(),
        "trade_id": uuid4(),
        "symbol": "AAPL",
        "side": "buy",
        "quantity": Decimal("1"),
        "order_type": "MKT",
        "client_order_id": uuid4(),
    }
    base.update(overrides)
    return NewOrder(**base)  # type: ignore[arg-type]


@pytest.fixture
def adapter_factory() -> tuple[IBKRAdapter, FakeIBClient]:
    fake = FakeIBClient()
    fake.configure_account_equity()
    brokerage = IBKRBrokerageModel.for_paper()
    adapter = IBKRAdapter(
        brokerage=brokerage,
        client_factory=lambda: fake,
    )
    return adapter, fake


@pytest.mark.asyncio
async def test_connect_marks_connected_and_starts_heartbeat(
    adapter_factory: tuple[IBKRAdapter, FakeIBClient],
) -> None:
    adapter, fake = adapter_factory
    await adapter.connect()
    try:
        assert adapter.state is ConnectionState.CONNECTED
        assert fake.connect_calls == 1
        assert adapter._heartbeat_task is not None
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_disconnect_is_idempotent(
    adapter_factory: tuple[IBKRAdapter, FakeIBClient],
) -> None:
    adapter, _fake = adapter_factory
    await adapter.connect()
    await adapter.disconnect()
    await adapter.disconnect()  # second call: no raise.
    assert adapter.state is ConnectionState.DISCONNECTED


@pytest.mark.asyncio
async def test_place_order_requires_client_order_id(
    adapter_factory: tuple[IBKRAdapter, FakeIBClient],
) -> None:
    adapter, _fake = adapter_factory
    await adapter.connect()
    try:
        order = _new_order(client_order_id=None)
        with pytest.raises(ValueError, match="client_order_id"):
            await adapter.place_order(order)
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_place_order_idempotent_on_repeat_client_order_id(
    adapter_factory: tuple[IBKRAdapter, FakeIBClient],
) -> None:
    adapter, fake = adapter_factory
    await adapter.connect()
    try:
        order = _new_order()
        first = await adapter.place_order(order)
        second = await adapter.place_order(order)
        assert first == second
        assert len(fake.placed_orders) == 1  # broker submission only once
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_place_order_rejects_unsupported_order_type(
    adapter_factory: tuple[IBKRAdapter, FakeIBClient],
) -> None:
    adapter, _fake = adapter_factory
    await adapter.connect()
    try:
        order = _new_order(order_type="TRAIL")
        with pytest.raises(UnsupportedOrderTypeError):
            await adapter.place_order(order)
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_get_account_equity_extracts_known_tags(
    adapter_factory: tuple[IBKRAdapter, FakeIBClient],
) -> None:
    adapter, fake = adapter_factory
    fake.configure_account_equity(
        net_liquidation=Decimal("75000"),
        cash=Decimal("25000"),
    )
    await adapter.connect()
    try:
        snap = await adapter.get_account_equity()
        assert snap.account_equity == Decimal("75000")
        assert snap.cash_balance == Decimal("25000")
        assert snap.mode == "paper"
        assert snap.snapshot_kind == "event"
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_get_position_returns_zero_quantity_for_unknown_symbol(
    adapter_factory: tuple[IBKRAdapter, FakeIBClient],
) -> None:
    adapter, _fake = adapter_factory
    await adapter.connect()
    try:
        pos = await adapter.get_position("UNKNOWN")
        assert pos.quantity == Decimal("0")
        assert pos.symbol == "UNKNOWN"
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_reconcile_fills_window_exhausted_raises() -> None:
    from datetime import timedelta

    from iguanatrader.shared.time import now as utc_now

    fake = FakeIBClient()
    adapter = IBKRAdapter(
        brokerage=IBKRBrokerageModel.for_paper(),
        client_factory=lambda: fake,
    )
    await adapter.connect()
    try:
        ancient = utc_now() - timedelta(days=10)
        with pytest.raises(BrokerWindowExhaustedError):
            async for _ in adapter.reconcile_fills(ancient):
                pass
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_resilient_reconnect_succeeds_on_third_attempt(
    adapter_factory: tuple[IBKRAdapter, FakeIBClient],
) -> None:
    adapter, fake = adapter_factory
    await adapter.connect()
    try:
        # Configure the fake to fail twice then succeed (third attempt wins).
        fake.connect_failures = 2
        adapter._last_disconnect_at = None  # reset
        with patch("asyncio.sleep") as mocked_sleep:
            mocked_sleep.return_value = None  # don't wait actual seconds
            await adapter._resilient_reconnect_loop()
        assert adapter.state is ConnectionState.CONNECTED
        # connect_calls = 1 initial + 2 failures + 1 success = 4
        assert fake.connect_calls == 4
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_resilient_reconnect_exhausted_returns_silently(
    adapter_factory: tuple[IBKRAdapter, FakeIBClient],
) -> None:
    """5 failed attempts → emit killswitch, no further retries."""
    adapter, fake = adapter_factory
    await adapter.connect()
    try:
        fake.connect_failures = 99  # all attempts will fail
        with patch("asyncio.sleep") as mocked_sleep:
            mocked_sleep.return_value = None
            await adapter._resilient_reconnect_loop()
        # Adapter state is left RECONNECTING (mark_connected never called).
        assert adapter.state is ConnectionState.RECONNECTING
        # Initial connect = 1, plus 5 failed attempts = 6 connect_calls total.
        assert fake.connect_calls == 6
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_resilient_reconnect_auth_failure_short_circuits(
    adapter_factory: tuple[IBKRAdapter, FakeIBClient],
) -> None:
    """Auth failure trips the killswitch on attempt 1 — no further attempts."""
    adapter, fake = adapter_factory
    await adapter.connect()
    try:
        fake.connect_should_raise_auth = True
        baseline_calls = fake.connect_calls
        with patch("asyncio.sleep") as mocked_sleep:
            mocked_sleep.return_value = None
            await adapter._resilient_reconnect_loop()
        # Only one connect attempt in the loop body (regardless of MAX_RECONNECT_ATTEMPTS).
        assert fake.connect_calls == baseline_calls + 1
    finally:
        await adapter.disconnect()
