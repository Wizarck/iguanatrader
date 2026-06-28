"""DaemonLifecycleService — drain + reconcile coordinator (slice
``dual-daemon-mode-toggle-and-reconcile`` + ``dual-daemon-followups``).

The single ``trading_daemon`` process becomes mode-aware: each daemon
runs with its own ``mode`` (paper or live) and reacts to mode-scoped
drain/reconcile requests it polls from the ``tenant_trading_modes`` row.

Cross-process control: the API process and the ``trading_daemon``
process are SEPARATE containers, and the :class:`MessageBus` is
in-process only — it cannot carry an event from the API to a daemon.
So drain + reconcile are driven by :meth:`poll_for_state_changes`
(called from the 10s heartbeat cron), which watches the
``tenant_trading_modes`` row that the API endpoints write:

* toggle-off (``enabled`` false) → :meth:`_drain_pending_proposals` —
  bulk-reject pending_approval proposals for the matching mode, stamp
  ``rejection_reason='daemon_drained'``. IBKR-side orders untouched
  (IBKR is the authoritative book; we only refuse to create new ones).

* ``pending_reconcile_at`` advance → :meth:`reconcile_with_ibkr`.

:meth:`reconcile_with_ibkr` is the on-demand + on-boot reconcile entry
point. Three steps:

1. Fills catch-up — delegate to existing :meth:`TradingService.startup_reconcile`.
2. Equity snapshot — fresh row tagged ``snapshot_kind='event'``.
3. Position diff (slice ``dual-daemon-followups`` Phase-2.5) — close
   any local open trade whose ``symbol`` is absent from
   :meth:`BrokerPort.list_positions`. The close uses
   ``exit_reason='ibkr_reconcile'`` (migration 0030 extended the CHECK
   constraint to accept the new sentinel).

Each daemon process holds one instance scoped to its ``(tenant_id,
mode)`` pair; the poll loads only that pair's row, so the paper daemon
never reacts to live state and vice versa.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import structlog
from sqlalchemy import update

from iguanatrader.contexts.trading.models import EquitySnapshot, TradeProposal
from iguanatrader.shared.contextvars import session_var
from iguanatrader.shared.time import now as utc_now

if TYPE_CHECKING:
    from iguanatrader.contexts.trading.ports import BrokerPort
    from iguanatrader.contexts.trading.repository import (
        EquitySnapshotRepository,
        TradeRepository,
        TradingModeRepository,
    )
    from iguanatrader.contexts.trading.service import TradingService

log = structlog.get_logger("iguanatrader.contexts.trading.daemon_lifecycle")


class DaemonLifecycleService:
    """Drain + reconcile coordinator bound to one (tenant, mode); poll-driven."""

    def __init__(
        self,
        *,
        mode: str,
        tenant_id: UUID,
        trading_service: TradingService,
        trading_mode_repo: TradingModeRepository,
        broker: BrokerPort,
        equity_repo: EquitySnapshotRepository,
        trade_repo: TradeRepository | None = None,
    ) -> None:
        if mode not in ("paper", "live"):
            raise ValueError(f"mode must be 'paper' or 'live', got {mode!r}")
        self._mode = mode
        self._tenant_id = tenant_id
        self._trading_service = trading_service
        self._trading_mode_repo = trading_mode_repo
        self._broker = broker
        self._equity_repo = equity_repo
        # ``trade_repo`` is optional for backwards-compat with callers
        # that wired the service before Phase-2.5 added position
        # reconcile. The reconcile step gracefully no-ops when None so
        # tests built against the original constructor signature still
        # construct the service.
        self._trade_repo = trade_repo
        # Phase 3.5 cross-process poll watermarks. Initialised on the
        # first ``poll_for_state_changes`` call to the current column
        # values so historical state does not retroactively fire drain
        # or reconcile on daemon boot.
        self._last_toggle_handled: datetime | None = None
        self._last_reconcile_handled: datetime | None = None
        self._poll_initialised = False

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
                "bind the session contextvar before invoking drain"
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

    async def poll_for_state_changes(self) -> None:
        """Detect API-side toggle / reconcile requests + react.

        Phase 3.5 cross-process bridge. Called from the 10s heartbeat
        cron so the daemon picks up changes within ~10 seconds even
        when the in-process bus cannot cross container boundaries.

        Logic:

        1. Load the ``tenant_trading_modes`` row.
        2. On the FIRST call, initialise watermarks from the current
           column values (no retroactive trigger on boot).
        3. If ``last_toggled_at`` is newer than the watermark, advance
           the watermark + run drain when ``enabled=false``. (Enabled
           toggles do not need a daemon-side action — the propose-tick
           gate picks them up on the next cron fire.)
        4. If ``pending_reconcile_at`` is newer than the watermark,
           advance the watermark + run reconcile.

        Silently no-ops when ``session_var`` is unset (the heartbeat
        cron sometimes fires before the session contextvar is bound
        on a fresh boot — drain/reconcile will catch up on the next
        tick).
        """
        session = session_var.get()
        if session is None:
            return
        row = await self._trading_mode_repo.load_for_polling(
            tenant_id=self._tenant_id, mode=self._mode
        )
        if row is None:
            return

        if not self._poll_initialised:
            self._last_toggle_handled = row.last_toggled_at
            self._last_reconcile_handled = row.pending_reconcile_at
            self._poll_initialised = True
            return

        # Toggle-change detection. ``last_toggled_at`` is NOT NULL
        # (defaulted at insert + restamped on every set) so a simple
        # > compare is safe once the watermark is initialised.
        if self._last_toggle_handled is None or row.last_toggled_at > self._last_toggle_handled:
            self._last_toggle_handled = row.last_toggled_at
            if not row.enabled:
                log.info(
                    "daemon_lifecycle.poll.toggle_off_detected",
                    mode=self._mode,
                    tenant_id=str(self._tenant_id),
                )
                await self._drain_pending_proposals(reason="daemon_drained")

        # Reconcile-pending detection. ``pending_reconcile_at`` is
        # nullable; we treat NULL → non-NULL as the only fire path.
        if row.pending_reconcile_at is not None and (
            self._last_reconcile_handled is None
            or row.pending_reconcile_at > self._last_reconcile_handled
        ):
            self._last_reconcile_handled = row.pending_reconcile_at
            log.info(
                "daemon_lifecycle.poll.reconcile_pending_detected",
                mode=self._mode,
                tenant_id=str(self._tenant_id),
                pending_reconcile_at=row.pending_reconcile_at.isoformat(),
            )
            await self.reconcile_with_ibkr()

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
        except Exception as exc:
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
        except Exception as exc:
            log.warning(
                "daemon_lifecycle.reconcile.equity_failed",
                error=str(exc),
                correlation_id=str(corr),
            )

        # 3. Position-side reconcile — slice ``dual-daemon-followups``
        # Phase-2.5. Pulls the full IBKR position list, compares the
        # symbol set to the daemon's local open-trade view, and closes
        # any local row whose symbol is absent broker-side. Uses
        # ``exit_reason='ibkr_reconcile'`` (migration 0030 added the
        # sentinel to ``ck_trades_exit_reason_allowed``).
        try:
            await self._reconcile_positions(correlation_id=corr)
        except Exception as exc:
            log.warning(
                "daemon_lifecycle.reconcile.positions_failed",
                error=str(exc),
                correlation_id=str(corr),
            )

        # Audit #2/#27: commit the reconcile's writes at this unit-of-work
        # boundary. The daemon runs on a long-lived session that is otherwise
        # only committed per-fill inside ``startup_reconcile`` (#308); the
        # equity snapshot (step 2) and the ``ibkr_reconcile`` orphan-close
        # mutations (step 3) are only ``add``-ed / mutated in the session here,
        # so without this commit they are logged as done but rolled back when
        # the session eventually closes — the orphan trades stay ``open`` and
        # the equity row never lands. Mirrors the per-tick commit in
        # ``EquitySnapshotSweepService.sweep`` / ``reconcile_fills_handler``.
        try:
            session = session_var.get(None)
            if session is not None:
                await session.commit()
        except Exception as exc:
            log.warning(
                "daemon_lifecycle.reconcile.commit_failed",
                error=str(exc),
                correlation_id=str(corr),
            )

        log.info(
            "daemon_lifecycle.reconcile.completed",
            mode=self._mode,
            tenant_id=str(self._tenant_id),
            correlation_id=str(corr),
        )

    async def _reconcile_positions(self, *, correlation_id: UUID) -> None:
        """Reconcile local open trades against IBKR's position book.

        Two effects, both driven by a single :meth:`BrokerPort.list_positions`
        read (the broker's authoritative open-position book):

        1. **Marks** — for every local open trade whose ``symbol`` IBKR still
           holds, stamp the broker's ``avgCost`` onto ``avg_entry_price`` + its
           mark-to-market onto ``unrealized_pnl`` (+ ``marks_updated_at``). This
           is the ONLY reliable source for a position whose entry fills predate
           the ``reqExecutions`` window: the fills never reconcile, so the
           positions API would otherwise show "pendiente de ejecución" forever.
           The columns are on the append-only whitelist (migration 0040).
        2. **Orphan close** — any local row whose ``symbol`` does NOT appear in
           the broker set is closed via the ``ibkr_reconcile`` exit-reason path.

        Idempotency: a second reconcile re-stamps marks (cheap, monotonic) and
        finds orphans already ``state='closed'``. We rely on the slice-3
        append-only listener's whitelist to permit both UPDATEs.

        No-op when ``self._trade_repo`` is None (backwards-compat for
        tests that constructed the service without Phase-2.5 wiring).
        """
        if self._trade_repo is None:
            log.info(
                "daemon_lifecycle.reconcile.positions_skipped",
                reason="trade_repo_unwired",
                correlation_id=str(correlation_id),
            )
            return

        broker_positions = await self._broker.list_positions()
        # Non-zero broker positions keyed by symbol. ``list_positions`` already
        # filters zero-quantity rows adapter-side, but guard again defensively.
        marks_by_symbol = {pos.symbol: pos for pos in broker_positions if pos.quantity != 0}
        broker_symbols = set(marks_by_symbol)

        local_open = await self._trade_repo.list_open_for_tenant()
        # Filter to this daemon's mode — the same TradeRepository is
        # shared by both paper + live daemons in a multi-process
        # deployment; per-mode session isolation is provided by the
        # session_var binding, but a defensive filter keeps the diff
        # honest if a future call site changes session scoping.
        local_mine = [t for t in local_open if t.mode == self._mode]

        # 1. Stamp broker marks on the matched (still-held) positions. IBKR
        # aggregates by symbol, so when >1 local trade shares a symbol they all
        # receive the same avg/uPnL (acceptable for the MVP single-position-
        # per-symbol watchlist; revisit if partial scaling lands).
        now = utc_now()
        marked = 0
        for trade in local_mine:
            pos = marks_by_symbol.get(trade.symbol)
            if pos is None:
                continue
            trade.avg_entry_price = pos.average_price
            trade.unrealized_pnl = pos.unrealized_pnl
            trade.marks_updated_at = now
            marked += 1

        # 2. Orphan close — symbols the broker no longer holds.
        orphans = [t for t in local_mine if t.symbol not in broker_symbols]
        for trade in orphans:
            trade.state = "closed"
            trade.exit_reason = "ibkr_reconcile"
            trade.closed_at = now

        log.info(
            "daemon_lifecycle.reconcile.positions_reconciled",
            mode=self._mode,
            correlation_id=str(correlation_id),
            local_open_count=len(local_mine),
            broker_symbol_count=len(broker_symbols),
            marks_updated=marked,
            closed_count=len(orphans),
            closed_symbols=[t.symbol for t in orphans],
        )


__all__ = ["DaemonLifecycleService"]
