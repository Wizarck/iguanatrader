"""Equity-snapshot sweep service.

Slice ``equity-snapshot-daemon``. Queries :class:`BrokerPort` for the
current account equity and persists an :class:`EquitySnapshot` row
plus emits :class:`EquityUpdated`. Registered as a cron job by
:meth:`OrchestrationService.bootstrap_routines` (every 15 minutes
during US market hours, mirroring the trailing-stops cadence).

This unblocks the max-drawdown protection in K1: prior to this slice,
equity snapshots were ONLY persisted on terminal fills (when a trade
closes), so the rolling drawdown query in
:class:`RiskRepository._compute_drawdown_pct` saw zero
or stale data and the protection silently passed every check.

Per-tenant scoping mirrors the cost-snapshot publisher pattern in
``observability/cost_dashboard_publisher.py``: list non-deleted
tenants, switch context for each, write the row. The broker fake in
tests is configurable per-tenant so the cross-tenant guard in the
:func:`tenant_listener` doesn't trip.

Failure isolation: a broker error for one tenant is counted in
``broker_errors`` with the tenant id logged + the sweep continues to
the next tenant. The whole-sweep transaction is committed once at
the end (one cron tick = one transactional unit, same shape as
trailing-stops).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

from sqlalchemy import select

from iguanatrader.contexts.trading.events import EquityUpdated
from iguanatrader.contexts.trading.models import EquitySnapshot
from iguanatrader.contexts.trading.ports import BrokerPort
from iguanatrader.contexts.trading.repository import EquitySnapshotRepository
from iguanatrader.persistence.models import Tenant
from iguanatrader.shared.contextvars import session_var, with_tenant_context
from iguanatrader.shared.messagebus import MessageBus
from iguanatrader.shared.time import now as utc_now

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EquitySnapshotSweepResult:
    """Counters + duration returned from :meth:`EquitySnapshotSweepService.sweep`."""

    tenants_evaluated: int
    snapshots_persisted: int
    broker_errors: int
    duration_ms: int


class EquitySnapshotSweepService:
    """Per-tick orchestrator: tenants → broker.get_account_equity → row + event.

    The service is stateless beyond its injected dependencies; the
    cron caller instantiates one per registration and reuses it.
    """

    def __init__(
        self,
        *,
        broker: BrokerPort,
        equity_repo: EquitySnapshotRepository,
        bus: MessageBus,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._broker = broker
        self._equity_repo = equity_repo
        self._bus = bus
        self._clock = clock

    async def sweep(self) -> EquitySnapshotSweepResult:
        """Iterate tenants, capture equity, persist snapshot, emit event."""
        started_at = self._clock()
        tenant_ids = await self._list_tenant_ids()

        persisted = 0
        errors = 0

        sess = session_var.get()
        session = cast("AsyncSession", sess) if sess is not None else None

        for tenant_id in tenant_ids:
            try:
                async with with_tenant_context(tenant_id):
                    equity_value = await self._broker.get_account_equity()
                    snapshot_id = uuid4()
                    snapshot = EquitySnapshot(
                        id=snapshot_id,
                        tenant_id=equity_value.tenant_id,
                        mode=equity_value.mode,
                        account_equity=equity_value.account_equity,
                        cash_balance=equity_value.cash_balance,
                        realized_pnl_today=equity_value.realized_pnl_today,
                        unrealized_pnl=equity_value.unrealized_pnl,
                        currency=equity_value.currency,
                        snapshot_kind=equity_value.snapshot_kind,
                    )
                    await self._equity_repo.add(snapshot)
                    # Commit INSIDE the tenant context so the slice-3
                    # tenant_listener (which fires on INSERT during
                    # flush) sees a bound tenant_id_var. Per-tenant
                    # commits also implement failure isolation: a
                    # later tenant's broker outage does not roll back
                    # earlier tenants' snapshots.
                    if session is not None:
                        await session.commit()
                    await self._bus.publish(
                        EquityUpdated(
                            tenant_id=equity_value.tenant_id,
                            equity_snapshot_id=snapshot_id,
                        )
                    )
                persisted += 1
            except Exception as exc:
                logger.warning(
                    "trading.equity_snapshot_sweep.tenant_failed: %s: %s",
                    type(exc).__name__,
                    exc,
                    extra={"tenant_id": str(tenant_id)},
                )
                errors += 1
                if session is not None:
                    # Discard the failed-tenant's pending INSERT so
                    # the next tenant's session is clean.
                    await session.rollback()
                continue

        ended_at = self._clock()
        duration_ms = int((ended_at - started_at).total_seconds() * 1000)

        logger.info(
            "trading.equity_snapshot_sweep.completed",
            extra={
                "tenants_evaluated": len(tenant_ids),
                "snapshots_persisted": persisted,
                "broker_errors": errors,
                "duration_ms": duration_ms,
            },
        )

        return EquitySnapshotSweepResult(
            tenants_evaluated=len(tenant_ids),
            snapshots_persisted=persisted,
            broker_errors=errors,
            duration_ms=duration_ms,
        )

    @staticmethod
    async def _list_tenant_ids() -> list[UUID]:
        """Read all non-soft-deleted tenant ids — system context.

        :class:`Tenant` is non-tenant-scoped so the slice-3 listener
        does not filter; the explicit query gives the sweep a stable
        iteration list even without a bound ``tenant_id_var`` at the
        outer call site (the cron caller).
        """
        sess = session_var.get()
        if sess is None:
            return []
        session = cast("AsyncSession", sess)
        stmt = select(Tenant.id).where(Tenant.deleted_at.is_(None))
        result = await session.execute(stmt)
        out: list[UUID] = []
        for row in result.all():
            raw = row[0]
            out.append(raw if isinstance(raw, UUID) else UUID(str(raw)))
        return out


__all__ = [
    "EquitySnapshotSweepResult",
    "EquitySnapshotSweepService",
]
