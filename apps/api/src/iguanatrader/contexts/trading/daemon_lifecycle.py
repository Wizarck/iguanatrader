"""DaemonLifecycleService — drain + reconcile coordinator (slice
``dual-daemon-mode-toggle-and-reconcile``).

The single ``trading_daemon`` process becomes mode-aware: each daemon
runs with its own ``mode`` (paper or live) and listens for bus events
addressed to that mode.

Bus subscriptions registered by :meth:`register_subscriptions`:

* :class:`DaemonDrainRequested` → :meth:`_drain_handler` — bulk-reject
  pending_approval proposals for the matching mode, stamp
  ``rejection_reason='daemon_drained'``. IBKR-side orders untouched
  (IBKR is the authoritative book; we only refuse to create new ones).

* :class:`DaemonReconcileRequested` → :meth:`_reconcile_handler` —
  delegate to :meth:`reconcile_with_ibkr`.

:meth:`reconcile_with_ibkr` is the on-demand + on-boot reconcile entry
point. First cut: fills + equity snapshot. Position-side reconcile
(closing local trades absent from IBKR's book with
``exit_reason='ibkr_reconcile'``) is deferred to Phase-2.5 follow-up —
needs ``BrokerPort.list_positions()`` + a fake-adapter test fixture.

Each daemon process holds one instance scoped to its ``(tenant_id,
mode)`` pair. Both subscriptions filter on ``event.mode == self._mode``
so the paper daemon ignores live events and vice versa.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import update

from iguanatrader.contexts.trading.events import (
    DaemonDrainRequested,
    DaemonReconcileRequested,
)
from iguanatrader.contexts.trading.models import EquitySnapshot, TradeProposal
from iguanatrader.shared.contextvars import session_var
from iguanatrader.shared.time import now as utc_now

if TYPE_CHECKING:
    from iguanatrader.contexts.trading.ports import BrokerPort
    from iguanatrader.contexts.trading.repository import (
        EquitySnapshotRepository,
        TradingModeRepository,
    )
    from iguanatrader.contexts.trading.service import TradingService
    from iguanatrader.shared.messagebus import MessageBus

log = structlog.get_logger("iguanatrader.contexts.trading.daemon_lifecycle")


class DaemonLifecycleService:
    """Drain + reconcile bus handler bound to one (tenant, mode)."""

    def __init__(
        self,
        *,
        mode: str,
        tenant_id: UUID,
        bus: MessageBus,
        trading_service: TradingService,
        trading_mode_repo: TradingModeRepository,
        broker: BrokerPort,
        equity_repo: EquitySnapshotRepository,
    ) -> None:
        if mode not in ("paper", "live"):
            raise ValueError(f"mode must be 'paper' or 'live', got {mode!r}")
        self._mode = mode
        self._tenant_id = tenant_id
        self._bus = bus
        self._trading_service = trading_service
        self._trading_mode_repo = trading_mode_repo
        self._broker = broker
        self._equity_repo = equity_repo

    def register_subscriptions(self) -> None:
        """Subscribe ``DaemonDrainRequested`` + ``DaemonReconcileRequested``.

        Both use ``idempotent=True`` per slice-2 D1; toggle bounce or
        retry-on-failure won't trigger duplicate work.
        """
        self._bus.subscribe(
            DaemonDrainRequested,
            self._drain_handler,
            idempotent=True,
        )
        self._bus.subscribe(
            DaemonReconcileRequested,
            self._reconcile_handler,
            idempotent=True,
        )
        log.info(
            "daemon_lifecycle.subscriptions_registered",
            mode=self._mode,
            tenant_id=str(self._tenant_id),
        )

    async def _drain_handler(self, event: DaemonDrainRequested) -> None:
        if event.mode != self._mode:
            return  # ignored — event is for the other daemon
        if event.tenant_id != self._tenant_id:
            return  # ignored — event is for a different tenant
        await self._drain_pending_proposals(reason=event.reason or "daemon_drained")

    async def _reconcile_handler(self, event: DaemonReconcileRequested) -> None:
        if event.mode != self._mode:
            return
        if event.tenant_id != self._tenant_id:
            return
        await self.reconcile_with_ibkr(correlation_id=event.correlation_id)

    async def _drain_pending_proposals(self, *, reason: str) -> int:
        """Bulk-reject pending_approval proposals for this daemon's mode.

        Returns the count of rows updated (visibility for the structlog
        breadcrumb). Idempotent: a second drain in the same toggle cycle
        finds no pending rows and updates 0.
        """
        session = session_var.get()
        if session is None:
            raise LookupError(
                "session_var unset in _drain_pending_proposals; the daemon must "
                "set the session contextvar before bus delivery"
            )
        stmt = (
            update(TradeProposal)
            .where(TradeProposal.tenant_id == self._tenant_id)
            .where(TradeProposal.mode == self._mode)
            .where(TradeProposal.state == "pending_approval")
            .values(
                state="rejected",
                rejection_reason=reason,
                rejected_at=utc_now(),
            )
            .execution_options(synchronize_session=False)
        )
        result = await session.execute(stmt)
        rowcount = result.rowcount or 0
        log.info(
            "daemon_lifecycle.drain.completed",
            mode=self._mode,
            tenant_id=str(self._tenant_id),
            rejected_count=rowcount,
            reason=reason,
        )
        return rowcount

    async def reconcile_with_ibkr(
        self,
        *,
        correlation_id: UUID | None = None,
    ) -> None:
        """Reconcile local state with IBKR.

        First cut covers fills (delegates to existing
        :meth:`TradingService.startup_reconcile`) + equity snapshot
        (one new row tagged ``snapshot_kind='event'``). Position-side
        reconcile (closing local trades that IBKR no longer holds) is
        deferred to Phase-2.5; the spec acceptance test that asserts
        ``provenance='ibkr_reconcile'`` on closed local trades will be
        exercised once that follow-up lands.

        ``correlation_id`` flows into log entries so on-demand-button
        invocations can be traced from API call through to fill
        ingestion. ``None`` is used for boot-time reconcile.
        """
        corr = correlation_id or uuid4()
        log.info(
            "daemon_lifecycle.reconcile.started",
            mode=self._mode,
            tenant_id=str(self._tenant_id),
            correlation_id=str(corr),
        )

        # 1. Fills reconcile (existing flow — drains any broker fills
        # the daemon missed since the last persisted fill).
        try:
            await self._trading_service.startup_reconcile()
        except Exception as exc:  # noqa: BLE001 — best-effort; log + continue
            log.warning(
                "daemon_lifecycle.reconcile.fills_failed",
                error=str(exc),
                correlation_id=str(corr),
            )

        # 2. Equity snapshot — pull broker-side cash + equity, write a
        # row tagged ``snapshot_kind='event'`` so the equity-curve
        # dashboard reflects the reconcile point.
        try:
            equity_value = await self._broker.get_account_equity()
            snapshot = EquitySnapshot(
                id=uuid4(),
                tenant_id=self._tenant_id,
                mode=self._mode,
                account_equity=equity_value.account_equity,
                cash_balance=equity_value.cash_balance,
                realized_pnl_today=equity_value.realized_pnl_today,
                unrealized_pnl=equity_value.unrealized_pnl,
                currency=equity_value.currency,
                snapshot_kind="event",
            )
            await self._equity_repo.add(snapshot)
        except Exception as exc:  # noqa: BLE001 — best-effort; log + continue
            log.warning(
                "daemon_lifecycle.reconcile.equity_failed",
                error=str(exc),
                correlation_id=str(corr),
            )

        # 3. Position-side reconcile — DEFERRED (Phase-2.5). The
        # ``provenance='ibkr_reconcile'`` close path needs a new
        # ``BrokerPort.list_positions()`` method + a fake-adapter
        # fixture for tests + an extension to the ``exit_reason`` CHECK
        # constraint to allow the new sentinel. Tracked as task 2.5.x
        # in tasks.md.
        log.info(
            "daemon_lifecycle.reconcile.positions_skipped",
            reason="phase_2_5_deferred",
            correlation_id=str(corr),
        )

        log.info(
            "daemon_lifecycle.reconcile.completed",
            mode=self._mode,
            tenant_id=str(self._tenant_id),
            correlation_id=str(corr),
        )


__all__ = ["DaemonLifecycleService"]
