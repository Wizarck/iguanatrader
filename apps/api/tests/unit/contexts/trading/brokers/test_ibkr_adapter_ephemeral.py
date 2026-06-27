"""Ephemeral live-gateway connect-on-demand lifecycle (WS-4 / WS-F).

The ephemeral live model keeps the IBKR gateway DOWN between approved order
batches (a live gateway logs the owner out of the mobile app). The adapter must
therefore NOT run the persistent heartbeat/reconnect loop — an intentional
gateway-down period would otherwise walk ``_resilient_reconnect_loop`` to
exhaustion and TRIP THE KILL-SWITCH. Instead it connects on demand per lease via
``ensure_connected`` and verifies liveness right before the order.

These tests pin the real-money-critical lifecycle end to end:

* connect-on-demand + verify-before-trust;
* reuse the live connection within a lease window (one connect, not per order);
* a gateway recycled between leases is detected (stale ping) and the adapter
  reconnects against the fresh gateway, tearing the old socket down cleanly;
* fail-CLOSED (raise) when the gateway never comes up or the verify ping fails;
* NO persistent heartbeat/reconnect task is EVER started, and no kill-switch is
  tripped by the deliberately-down gateway (the whole point of the mode).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from iguanatrader.contexts.trading.brokers.ibkr_adapter import IBKRAdapter
from iguanatrader.contexts.trading.brokers.ibkr_brokerage_model import IBKRBrokerageModel
from iguanatrader.contexts.trading.ports import NewOrder
from iguanatrader.shared.errors import IntegrationError
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


class _RecordingBus:
    """Captures published events so tests can assert the kill-switch never fires."""

    def __init__(self) -> None:
        self.published: list[Any] = []

    async def publish(self, event: Any) -> None:
        self.published.append(event)


def _live_adapter(factory: Any, *, bus: Any = None) -> IBKRAdapter:
    return IBKRAdapter(
        brokerage=IBKRBrokerageModel.for_live(account_code="DU000000"),
        client_factory=factory,
        bus=bus,
    )


@pytest.mark.asyncio
async def test_ephemeral_lifecycle_connect_place_recycle_reconnect() -> None:
    """lease→connect→place→reuse→recycle→reconnect→place — the full e2e."""
    fakes: list[FakeIBClient] = []

    def factory() -> FakeIBClient:
        f = FakeIBClient()
        f.configure_account_equity()
        fakes.append(f)
        return f

    bus = _RecordingBus()
    adapter = _live_adapter(factory, bus=bus)

    # --- Lease #1: connect on demand + verify before trusting it. ----------
    await adapter.ensure_connected()
    assert adapter.state is ConnectionState.CONNECTED
    assert len(fakes) == 1
    assert fakes[0].connect_calls == 1
    # The defining safety property: NO persistent heartbeat / reconnect loop.
    assert adapter._heartbeat_task is None
    assert adapter._reconnect_task is None

    bid1 = await adapter.place_order(_new_order())
    assert bid1
    assert len(fakes[0].placed_orders) == 1

    # --- Same lease window: reuse the live connection (no re-lease/connect). -
    await adapter.ensure_connected()
    assert len(fakes) == 1  # did NOT build a second client
    assert fakes[0].connect_calls == 1

    # --- Gateway recycled between leases: the held socket is now stale, so its
    #     next heartbeat ping fails → ensure_connected reconnects on a fresh one.
    fakes[0].heartbeat_failures = 1
    await adapter.ensure_connected()
    assert adapter.state is ConnectionState.CONNECTED
    assert len(fakes) == 2  # reconnected against a fresh gateway
    assert fakes[0].disconnect_calls == 1  # old socket torn down cleanly

    bid2 = await adapter.place_order(_new_order())
    assert bid2
    assert len(fakes[1].placed_orders) == 1  # landed on the NEW gateway

    # --- Still no background loop, and the intentional down period NEVER
    #     escalated to the kill-switch. -------------------------------------
    assert adapter._heartbeat_task is None
    assert adapter._reconnect_task is None
    from iguanatrader.contexts.risk.events import RiskKillSwitchActivated

    assert not any(isinstance(e, RiskKillSwitchActivated) for e in bus.published)


@pytest.mark.asyncio
async def test_ensure_connected_fails_closed_when_gateway_never_comes_up() -> None:
    """A gateway that never accepts the socket → raise so the caller fails CLOSED."""
    fake = FakeIBClient()
    fake.connect_failures = 99  # connect_async raises every time

    adapter = _live_adapter(lambda: fake)
    with pytest.raises(Exception):  # noqa: B017 — any connect error fails closed
        await adapter.ensure_connected()
    assert adapter.state is ConnectionState.DISCONNECTED


@pytest.mark.asyncio
async def test_ensure_connected_tears_down_when_verify_ping_fails() -> None:
    """Connect succeeds but the verify ping fails → tear back down + raise."""
    fake = FakeIBClient()
    fake.heartbeat_failures = 1  # the post-connect verify ping fails once

    adapter = _live_adapter(lambda: fake)
    with pytest.raises(Exception):  # noqa: B017
        await adapter.ensure_connected()
    # Not trusted: torn back down so the next lease reconnects from scratch.
    assert adapter.state is ConnectionState.DISCONNECTED
    assert adapter._client is None
    assert fake.disconnect_calls == 1


@pytest.mark.asyncio
async def test_ensure_connected_refuses_after_shutdown() -> None:
    """Once the adapter is shutting down, ensure_connected must not reconnect."""
    fake = FakeIBClient()
    fake.configure_account_equity()
    adapter = _live_adapter(lambda: fake)

    await adapter.ensure_connected()
    await adapter.disconnect()  # sets the shutting-down flag

    with pytest.raises(IntegrationError):
        await adapter.ensure_connected()


@pytest.mark.asyncio
async def test_ephemeral_path_never_starts_persistent_heartbeat() -> None:
    """Regression guard: the ephemeral path must never spawn the background loop.

    The persistent ``_heartbeat_loop`` is the ONLY thing that can reach
    ``_resilient_reconnect_loop`` → the kill-switch. If a future change makes
    ``ensure_connected`` start it, an intentional gateway-down window would trip
    the kill-switch — exactly what this mode exists to avoid.
    """
    fake = FakeIBClient()
    fake.configure_account_equity()
    adapter = _live_adapter(lambda: fake)

    await adapter.ensure_connected()  # clean first connect
    assert adapter._heartbeat_task is None
    assert adapter._reconnect_task is None

    for _ in range(3):
        # Stale the held socket so the reuse ping fails → forces a reconnect.
        # (heartbeat_failures=1 is consumed by the reuse ping; the post-reconnect
        # verify ping then succeeds.)
        fake.heartbeat_failures = 1
        await adapter.ensure_connected()
        assert adapter.state is ConnectionState.CONNECTED
        assert adapter._heartbeat_task is None
        assert adapter._reconnect_task is None
