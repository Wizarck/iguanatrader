"""Integration tests — :class:`EquitySnapshotSweepService`.

Slice ``equity-snapshot-daemon``. Covers:

1. The sweep iterates every non-deleted tenant + persists one
   :class:`EquitySnapshot` per tenant + emits one
   :class:`EquityUpdated` per tenant.
2. A broker error on one tenant counts toward ``broker_errors`` but
   does NOT abort the rest (failure isolation).
3. The single commit per cron tick makes rows visible to subsequent
   sessions / dashboards (without it, rows stay in the flush buffer).

The fake broker is tenant-aware: it returns ``EquitySnapshotValue``
whose ``tenant_id`` matches the current ``tenant_id_var``, so the
slice-3 tenant_listener cross-tenant guard is satisfied.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.trading.equity_snapshot_sweep import (
    EquitySnapshotSweepService,
)
from iguanatrader.contexts.trading.events import EquityUpdated
from iguanatrader.contexts.trading.models import EquitySnapshot
from iguanatrader.contexts.trading.ports import (
    BrokerOrderId,
    BrokerPort,
    EquitySnapshotValue,
    NewOrder,
    Position,
)
from iguanatrader.contexts.trading.repository import EquitySnapshotRepository
from iguanatrader.persistence import Tenant
from iguanatrader.shared.contextvars import (
    session_var,
    tenant_id_var,
    with_tenant_context,
)
from iguanatrader.shared.messagebus import Event, MessageBus
from iguanatrader.shared.time import now as utc_now
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class _TenantAwareFakeBroker(BrokerPort):
    """In-memory broker that echoes the current ``tenant_id_var``.

    Each :meth:`get_account_equity` returns a fresh snapshot whose
    ``tenant_id`` is whichever tenant is bound to the context — so
    the sweep can iterate tenants without the cross-tenant guard
    tripping.

    Optionally raises on a configured tenant id (used to test the
    failure-isolation branch).
    """

    def __init__(self, *, raise_on_tenant: UUID | None = None) -> None:
        self._raise_on_tenant = raise_on_tenant
        self.calls: list[UUID] = []

    async def get_account_equity(self) -> EquitySnapshotValue:
        tid = tenant_id_var.get()
        assert tid is not None, "broker called outside tenant context"
        self.calls.append(tid)
        if self._raise_on_tenant is not None and tid == self._raise_on_tenant:
            raise RuntimeError(f"simulated broker outage for tenant {tid}")
        return EquitySnapshotValue(
            tenant_id=tid,
            mode="paper",
            account_equity=Decimal("12345.67"),
            cash_balance=Decimal("12000.00"),
            realized_pnl_today=Decimal("0"),
            unrealized_pnl=Decimal("345.67"),
            currency="USD",
            snapshot_kind="scheduled",
            captured_at=utc_now(),
        )

    async def place_order(self, order: NewOrder) -> BrokerOrderId:  # pragma: no cover
        raise NotImplementedError

    async def cancel_order(self, broker_order_id: BrokerOrderId) -> None:  # pragma: no cover
        raise NotImplementedError

    async def get_position(self, symbol: str) -> Position:  # pragma: no cover
        raise NotImplementedError

    async def list_positions(self) -> list[Position]:  # pragma: no cover
        return []

    async def reconcile_fills(self, since: datetime) -> Any:  # pragma: no cover
        if False:
            yield
        return


async def _seed_tenant(sf: async_sessionmaker[AsyncSession], name: str) -> UUID:
    tid = uuid4()
    async with sf() as s:
        s.add(Tenant(id=tid, name=name, feature_flags={}))
        await s.commit()
    return tid


class _RecordingBus(MessageBus):
    """MessageBus that captures every published event in-process."""

    def __init__(self) -> None:
        super().__init__()
        self.published: list[Event] = []

    async def publish(self, event: Event) -> None:
        self.published.append(event)
        await super().publish(event)


@pytest.mark.asyncio
async def test_sweep_persists_one_snapshot_per_tenant(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_a = await _seed_tenant(schema_session_factory, "tenant-a")
    tenant_b = await _seed_tenant(schema_session_factory, "tenant-b")

    broker = _TenantAwareFakeBroker()
    bus = _RecordingBus()

    async with schema_session_factory() as s:
        session_var.set(s)
        equity_repo = EquitySnapshotRepository()
        sweep = EquitySnapshotSweepService(
            broker=broker,
            equity_repo=equity_repo,
            bus=bus,
        )
        result = await sweep.sweep()

    assert result.tenants_evaluated == 2
    assert result.snapshots_persisted == 2
    assert result.broker_errors == 0
    assert set(broker.calls) == {tenant_a, tenant_b}

    # Verify rows committed (visible to a fresh session). Each tenant's
    # snapshots are queried under that tenant's context so the
    # tenant_listener's filter passes.
    for expected_tenant in (tenant_a, tenant_b):
        async with (
            with_tenant_context(expected_tenant),
            schema_session_factory() as s,
        ):
            rows = (await s.execute(select(EquitySnapshot))).scalars().all()
            assert len(rows) == 1, f"expected 1 snapshot for {expected_tenant}"
            assert rows[0].tenant_id == expected_tenant
            assert rows[0].snapshot_kind == "scheduled"
            assert rows[0].account_equity == Decimal("12345.67")

    # One EquityUpdated event per tenant
    equity_events = [e for e in bus.published if isinstance(e, EquityUpdated)]
    assert len(equity_events) == 2
    assert {e.tenant_id for e in equity_events} == {tenant_a, tenant_b}


@pytest.mark.asyncio
async def test_sweep_isolates_broker_failure_to_one_tenant(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_ok = await _seed_tenant(schema_session_factory, "tenant-ok")
    tenant_fail = await _seed_tenant(schema_session_factory, "tenant-fail")

    broker = _TenantAwareFakeBroker(raise_on_tenant=tenant_fail)
    bus = _RecordingBus()

    async with schema_session_factory() as s:
        session_var.set(s)
        equity_repo = EquitySnapshotRepository()
        sweep = EquitySnapshotSweepService(
            broker=broker,
            equity_repo=equity_repo,
            bus=bus,
        )
        result = await sweep.sweep()

    assert result.tenants_evaluated == 2
    assert result.snapshots_persisted == 1
    assert result.broker_errors == 1

    async with (
        with_tenant_context(tenant_ok),
        schema_session_factory() as s,
    ):
        rows = (await s.execute(select(EquitySnapshot))).scalars().all()
        assert len(rows) == 1
        assert rows[0].tenant_id == tenant_ok

    async with (
        with_tenant_context(tenant_fail),
        schema_session_factory() as s,
    ):
        rows = (await s.execute(select(EquitySnapshot))).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_sweep_zero_tenants_returns_zero_counters(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    broker = _TenantAwareFakeBroker()
    bus = _RecordingBus()

    async with schema_session_factory() as s:
        session_var.set(s)
        equity_repo = EquitySnapshotRepository()
        sweep = EquitySnapshotSweepService(
            broker=broker,
            equity_repo=equity_repo,
            bus=bus,
        )
        result = await sweep.sweep()

    assert result.tenants_evaluated == 0
    assert result.snapshots_persisted == 0
    assert result.broker_errors == 0
    assert broker.calls == []


@pytest.mark.asyncio
async def test_sweep_uses_tenant_context_for_broker_call(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Regression guard: the broker is invoked inside ``with_tenant_context``.

    Without this, ``EquitySnapshotValue.tenant_id`` would default to
    the most-recently-bound tenant (or fail outright) and the listener
    would reject the cross-tenant snapshot.
    """
    tenant = await _seed_tenant(schema_session_factory, "single")
    broker = _TenantAwareFakeBroker()
    bus = _RecordingBus()

    # Pre-condition: no tenant bound outside the sweep (the default
    # is None — the listener treats None as "not bound" and raises).
    async with schema_session_factory() as s:
        session_var.set(s)
        equity_repo = EquitySnapshotRepository()
        sweep = EquitySnapshotSweepService(broker=broker, equity_repo=equity_repo, bus=bus)
        assert tenant_id_var.get() is None
        await sweep.sweep()

    # Sweep internally bound the tenant — broker saw the right id
    assert broker.calls == [tenant]


# Patch in the `with_tenant_context` symbol so mypy doesn't drop the
# import as unused.
_ = with_tenant_context
