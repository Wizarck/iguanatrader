"""Tests for IBKRAdapter._post_reconnect_reconciliation (slice T2 design D5)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from iguanatrader.contexts.trading.brokers.ibkr_adapter import IBKRAdapter
from iguanatrader.contexts.trading.brokers.ibkr_brokerage_model import IBKRBrokerageModel
from iguanatrader.shared.time import now as utc_now

from tests._fakes.ib_async_fake import FakeIBClient


@pytest.fixture
def adapter_with_disconnect_marker() -> tuple[IBKRAdapter, FakeIBClient]:
    fake = FakeIBClient()
    adapter = IBKRAdapter(
        brokerage=IBKRBrokerageModel.for_paper(),
        client_factory=lambda: fake,
    )
    return adapter, fake


@pytest.mark.asyncio
async def test_post_reconnect_no_disconnect_returns_silently(
    adapter_with_disconnect_marker: tuple[IBKRAdapter, FakeIBClient],
) -> None:
    adapter, _fake = adapter_with_disconnect_marker
    await adapter.connect()
    try:
        adapter._last_disconnect_at = None
        # Should not raise.
        await adapter._post_reconnect_reconciliation()
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_post_reconnect_emits_catchup_for_unobserved_executions(
    adapter_with_disconnect_marker: tuple[IBKRAdapter, FakeIBClient],
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter, fake = adapter_with_disconnect_marker
    await adapter.connect()
    try:
        # Simulate a disconnect 5 minutes ago.
        adapter._last_disconnect_at = utc_now() - timedelta(minutes=5)
        # Two fills happened during the outage.
        fake.add_execution(symbol="AAPL", shares=Decimal("10"), price=Decimal("180"))
        fake.add_execution(symbol="MSFT", shares=Decimal("5"), price=Decimal("400"))
        with caplog.at_level("INFO"):
            await adapter._post_reconnect_reconciliation()
        catchup_events = [r for r in caplog.records if "broker.fill.catchup" in r.message]
        assert len(catchup_events) == 2
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_post_reconnect_idempotent_on_double_reconnect(
    adapter_with_disconnect_marker: tuple[IBKRAdapter, FakeIBClient],
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter, fake = adapter_with_disconnect_marker
    await adapter.connect()
    try:
        adapter._last_disconnect_at = utc_now() - timedelta(minutes=5)
        fake.add_execution(symbol="AAPL", shares=Decimal("10"), price=Decimal("180"))
        await adapter._post_reconnect_reconciliation()
        with caplog.at_level("INFO"):
            await adapter._post_reconnect_reconciliation()  # second pass
        catchup_events = [r for r in caplog.records if "broker.fill.catchup" in r.message]
        # Second reconciliation must NOT emit duplicate catchup events
        # (exec_id deduplication via _known_exec_ids).
        assert len(catchup_events) == 0
    finally:
        await adapter.disconnect()


@pytest.mark.asyncio
async def test_reconcile_fills_yields_fill_events_with_broker_exec_id(
    adapter_with_disconnect_marker: tuple[IBKRAdapter, FakeIBClient],
) -> None:
    adapter, fake = adapter_with_disconnect_marker
    await adapter.connect()
    try:
        order_uuid = uuid4()
        fake.add_execution(
            order_ref=str(order_uuid),
            symbol="AAPL",
            shares=Decimal("3"),
            price=Decimal("190"),
            commission=Decimal("0.50"),
        )
        since = utc_now() - timedelta(minutes=10)
        events = []
        async for ev in adapter.reconcile_fills(since):
            events.append(ev)
        assert len(events) == 1
        assert events[0].order_id == order_uuid
        assert events[0].fill_price == Decimal("190")
        assert events[0].quantity_filled == Decimal("3")
        assert events[0].broker_fill_id is not None
    finally:
        await adapter.disconnect()
