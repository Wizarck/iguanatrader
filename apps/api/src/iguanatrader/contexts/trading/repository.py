"""Per-entity repositories for the trading context.

Per design D7: each entity gets a :class:`BaseRepository` subclass.
Tenant filtering is automatic via the slice-3 ``tenant_listener`` on
every SELECT issued through the session bound to ``session_var``.

Slice T1 plants only :meth:`StrategyConfigRepository.upsert` concretely
(needed for FR2/FR3 surface area in the route stubs); other
repositories ship empty bodies and gain query helpers in slice T4.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select

from iguanatrader.contexts.trading.models import (
    DaemonHeartbeat,
    EquitySnapshot,
    Fill,
    Order,
    StrategyConfig,
    TenantTradingMode,
    Trade,
    TradeProposal,
)
from iguanatrader.shared.contextvars import tenant_id_var
from iguanatrader.shared.kernel import BaseRepository
from iguanatrader.shared.time import now as utc_now


class StrategyConfigRepository(BaseRepository):
    """Persistence operations for :class:`StrategyConfig` (FR1-FR5)."""

    async def upsert(
        self,
        *,
        symbol: str,
        strategy_kind: str,
        params: dict[str, Any],
        enabled: bool,
    ) -> StrategyConfig:
        """Insert or update the per-tenant per-symbol-per-kind config.

        Uniqueness key is ``(tenant_id, strategy_kind, symbol)``. On
        UPDATE the SQLAlchemy ``before_update`` event hook bumps
        :attr:`StrategyConfig.version` and emits the structlog event
        ``trading.config.changed``.
        """
        tenant_id = tenant_id_var.get()
        if tenant_id is None:
            raise LookupError(
                "tenant_id_var must be set before StrategyConfigRepository.upsert; "
                "call from a request scope or via with_tenant_context()"
            )

        stmt = (
            select(StrategyConfig)
            .where(StrategyConfig.strategy_kind == strategy_kind)
            .where(StrategyConfig.symbol == symbol)
        )
        result = await self.session.execute(stmt)
        existing: StrategyConfig | None = result.scalar_one_or_none()

        if existing is None:
            row = StrategyConfig(
                id=uuid4(),
                tenant_id=tenant_id,
                strategy_kind=strategy_kind,
                symbol=symbol,
                params=params,
                enabled=enabled,
                version=1,
            )
            self.session.add(row)
            return row

        existing.params = params
        existing.enabled = enabled
        # ``version`` is bumped by the ``before_update`` listener on
        # :class:`StrategyConfig`; do NOT increment here or the bump
        # would land twice.
        return existing

    async def get_by_id(self, strategy_config_id: UUID) -> StrategyConfig | None:
        """Return the config by id, or ``None`` if absent.

        Used by :meth:`_make_strategy_resolver` (slice T4-followup-
        market-data §2.10) to load a fresh snapshot per propose call.
        """
        stmt = select(StrategyConfig).where(StrategyConfig.id == strategy_config_id)
        result = await self.session.execute(stmt)
        return cast("StrategyConfig | None", result.scalars().first())

    async def list_enabled_for_symbol(self, symbol: str) -> list[StrategyConfig]:
        """Return enabled configs for the current tenant + ``symbol``.

        Used by the per-symbol propose loop in
        :meth:`OrchestrationService.bootstrap_routines`. Tenant filter
        is automatic via the slice-3 ``tenant_listener``.
        """
        stmt = (
            select(StrategyConfig)
            .where(StrategyConfig.symbol == symbol)
            .where(StrategyConfig.enabled.is_(True))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_tenant(self) -> list[StrategyConfig]:
        """List all strategy configs for the current tenant.

        Ordered ``(symbol ASC, strategy_kind ASC)`` — matches the v1 UI's
        deterministic-listing expectation. Tenant filter is automatic
        via the slice-3 ``tenant_listener``.
        """
        stmt = select(StrategyConfig).order_by(
            StrategyConfig.symbol.asc(),
            StrategyConfig.strategy_kind.asc(),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_first_enabled_by_symbol(self, symbol: str) -> StrategyConfig | None:
        """Return the oldest enabled config for ``symbol`` (or None).

        Backend allows multiple kinds per symbol (composite UNIQUE is
        ``(tenant_id, strategy_kind, symbol)``); the v1 GET-by-symbol UI
        resolves the ambiguity by picking the oldest-``created_at``
        enabled row. Multi-kind UI is a v1.5 follow-up
        (``strategies-multi-kind-ui``).
        """
        stmt = (
            select(StrategyConfig)
            .where(StrategyConfig.symbol == symbol)
            .where(StrategyConfig.enabled.is_(True))
            .order_by(StrategyConfig.created_at.asc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return cast("StrategyConfig | None", result.scalars().first())

    async def list_all_by_symbol(self, symbol: str) -> list[StrategyConfig]:
        """Return every config (enabled or disabled) for ``symbol``.

        Used by :meth:`disable_all_by_symbol` so the soft-disable touches
        every row a tenant owns for that symbol — including already-
        disabled rows (idempotent re-disable). Tenant filter is automatic.
        """
        stmt = select(StrategyConfig).where(StrategyConfig.symbol == symbol)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def disable_all_by_symbol(self, symbol: str) -> int:
        """Soft-disable every config for ``symbol`` (set ``enabled=False``).

        Returns the number of rows touched. Performed via per-row UPDATE
        through the ORM (NOT a bulk ``update().where()`` statement) so:

        * The slice-3 ``tenant_listener`` filters the preceding SELECT to
          rows the caller's tenant owns (bulk UPDATE bypasses the listener).
        * The ``StrategyConfig.before_update`` hook fires per row, bumping
          ``version`` and emitting ``trading.config.changed``.
        * No DELETE is issued — audit history is preserved.

        Rows already at ``enabled=False`` are kept as-is (no version bump
        if nothing actually changed).
        """
        rows = await self.list_all_by_symbol(symbol)
        touched = 0
        for row in rows:
            if row.enabled:
                row.enabled = False
                touched += 1
        return touched


class TradeProposalRepository(BaseRepository):
    """Persistence operations for :class:`TradeProposal` (slice T4).

    Slice ``dual-daemon-mode-toggle-and-reconcile`` (migration 0028)
    promotes 3 columns to the append-only whitelist (``state`` +
    ``rejection_reason`` + ``rejected_at``) so the approval handlers +
    the daemon drain logic can advance the proposal lifecycle without
    breaking the otherwise-strict append-only contract. The bus events
    (:class:`ProposalApproved` / :class:`ProposalRejected`) remain the
    cross-context truth — the new columns are a row-level denormalisation
    so ``pending_proposals_count`` is an O(1) WHERE filter instead of a
    LEFT JOIN against ``approval_decisions``.
    """

    async def get_by_id(self, proposal_id: UUID) -> TradeProposal | None:
        """Return the proposal with the given id, or ``None`` if absent.

        Used by :meth:`TradingService.execute_on_approval_handler` to
        load the proposal at execute time. Tenant filtering is automatic
        via the session's tenant_listener.
        """
        stmt = select(TradeProposal).where(TradeProposal.id == proposal_id)
        result = await self.session.execute(stmt)
        return cast("TradeProposal | None", result.scalars().first())

    async def list_for_tenant(self) -> list[TradeProposal]:
        """List all proposals for the current tenant (slice proposals-list-endpoint).

        Tenant filter automatic via slice-3 ``tenant_listener``. Ordered
        ``created_at DESC`` (most-recent first); pagination v2.
        """
        stmt = select(TradeProposal).order_by(TradeProposal.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def set_state(
        self,
        *,
        proposal_id: UUID,
        state: str,
        rejection_reason: str | None = None,
    ) -> TradeProposal | None:
        """Transition a proposal to ``approved`` / ``rejected`` / ``expired``.

        Called from the approval handlers (on bus events
        :class:`ProposalApproved` / :class:`ProposalRejected`) and the
        daemon drain path. Sets ``rejected_at`` when ``state`` is
        ``rejected`` or ``expired``; otherwise leaves it NULL. Returns
        ``None`` if the proposal does not exist (caller can decide
        whether that is a hard error or a benign idempotent skip).
        """
        proposal = await self.get_by_id(proposal_id)
        if proposal is None:
            return None
        proposal.state = state
        proposal.rejection_reason = rejection_reason
        if state in ("rejected", "expired"):
            from iguanatrader.shared.time import now as utc_now

            proposal.rejected_at = utc_now()
        return proposal

    async def set_risk_assessment(
        self,
        *,
        proposal_id: UUID,
        risk_score: int,
        risk_flags: list[str],
        risk_rationale: str,
        risk_model: str,
    ) -> TradeProposal | None:
        """Persist an :class:`ProposalRiskAssessment` onto the proposal row.

        Called by the slice ``a2-risk-review-persist`` persister adapter
        on every above-threshold :class:`ProposalCreated`. Stamps
        ``risk_generated_at`` from the wall clock so multiple sequential
        assessments on the same proposal (regeneration path, future MCP
        force-re-review) keep a coherent timestamp without the caller
        having to plumb one through. Returns ``None`` when the proposal
        does not exist — caller treats that as a benign skip (the
        proposal may have been deleted in the gap between bus dispatch
        and persister invocation).
        """
        proposal = await self.get_by_id(proposal_id)
        if proposal is None:
            return None
        from iguanatrader.shared.time import now as utc_now

        proposal.risk_score = risk_score
        proposal.risk_flags = list(risk_flags)
        proposal.risk_rationale = risk_rationale
        proposal.risk_generated_at = utc_now()
        proposal.risk_model = risk_model
        return proposal


class TradeRepository(BaseRepository):
    """Persistence operations for :class:`Trade` (slice T4)."""

    async def add(self, trade: Trade) -> None:
        """Persist a new :class:`Trade` row."""
        self.session.add(trade)

    async def get_by_id(self, trade_id: UUID) -> Trade | None:
        stmt = select(Trade).where(Trade.id == trade_id)
        result = await self.session.execute(stmt)
        return cast("Trade | None", result.scalars().first())

    async def list_for_tenant(self) -> list[Trade]:
        """List all trades for the current tenant (slice trades-read-endpoints).

        Tenant filter automatic via slice-3 ``tenant_listener``. Ordered
        by ``created_at DESC`` (most-recent first); pagination is v2.
        """
        stmt = select(Trade).order_by(Trade.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_open_for_tenant(self) -> list[Trade]:
        """List live-position trades for the current tenant.

        Per slice ``trade-state-machine-redesign``: "live" means
        ``state IN ('open', 'closing')`` — ``open`` covers entry-pending
        and entry-filled-no-exit-yet; ``closing`` covers exit-order-
        submitted-but-not-yet-filled. Both represent positions the
        broker still holds. Ordered ``opened_at DESC``; tenant filter
        is automatic via the slice-3 ``tenant_listener``.
        """
        stmt = (
            select(Trade)
            .where(Trade.state.in_(("open", "closing")))
            .order_by(Trade.opened_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_state(
        self,
        trade_id: UUID,
        *,
        state: str,
        closed_at: Any | None = None,
        exit_reason: str | None = None,
        realised_pnl: Decimal | None = None,
    ) -> None:
        """Update ``trades.state`` and (optionally) the close-flow columns.

        All four mutable columns are on the slice-0015 append-only
        whitelist (``state, closed_at, exit_reason, realised_pnl``) so
        a single call can transition a trade to its terminal close in
        one UPDATE. None-valued kwargs leave the column untouched —
        the caller composes only what changes.
        """
        trade = await self.get_by_id(trade_id)
        if trade is None:
            return
        trade.state = state
        if closed_at is not None:
            trade.closed_at = closed_at
        if exit_reason is not None:
            trade.exit_reason = exit_reason
        if realised_pnl is not None:
            trade.realised_pnl = realised_pnl


class OrderRepository(BaseRepository):
    """Persistence operations for :class:`Order` (slice T4)."""

    async def add(self, order: Order) -> None:
        self.session.add(order)

    async def get_by_id(self, order_id: UUID) -> Order | None:
        stmt = select(Order).where(Order.id == order_id)
        result = await self.session.execute(stmt)
        return cast("Order | None", result.scalars().first())

    async def get_by_proposal_id(self, proposal_id: UUID) -> Order | None:
        """Used by :meth:`execute_on_approval_handler` for idempotency.

        ``Order`` carries ``trade_id`` (not ``proposal_id``) so we
        traverse the ``Order → Trade.proposal_id`` join. If a row
        exists for ``proposal_id``, the handler short-circuits without
        re-submitting to the broker.
        """
        stmt = (
            select(Order)
            .join(Trade, Order.trade_id == Trade.id)
            .where(Trade.proposal_id == proposal_id)
        )
        result = await self.session.execute(stmt)
        return cast("Order | None", result.scalars().first())

    async def get_by_broker_order_id(self, broker_order_id: str) -> Order | None:
        """Used by :meth:`reconcile_fills_handler` to map a fill back to its order."""
        stmt = select(Order).where(Order.broker_order_id == broker_order_id)
        result = await self.session.execute(stmt)
        return cast("Order | None", result.scalars().first())

    async def list_open_for_tenant(self) -> list[Order]:
        """List orders in an open state for the current tenant.

        ``state in {'new', 'submitted', 'partially_filled'}``, ordered
        ``created_at DESC``. Tenant filter is automatic via the
        slice-3 ``tenant_listener``.
        """
        open_states = ("new", "submitted", "partially_filled")
        stmt = select(Order).where(Order.state.in_(open_states)).order_by(Order.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_trade(self, trade_id: UUID) -> list[Order]:
        """List all orders (entry + exit) for a given trade.

        Ordered ``created_at ASC`` (chronological) so the entry order
        is first and any exit order follows. Used by the close-flow
        service (slice ``trade-close-flow-exit-pathway``) to compute
        realised P&L across the trade's full fill history.
        """
        stmt = select(Order).where(Order.trade_id == trade_id).order_by(Order.created_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class FillRepository(BaseRepository):
    """Persistence operations for :class:`Fill` (slice T4)."""

    async def add(self, fill: Fill) -> None:
        self.session.add(fill)

    async def exists_by_broker_fill_id(self, broker_fill_id: str) -> bool:
        """Idempotency check for :meth:`reconcile_fills_handler`.

        IBKR's ``exec_id`` is broker-stable; arriving twice means the
        handler should skip (the row is already persisted).
        """
        stmt = select(Fill.id).where(Fill.broker_fill_id == broker_fill_id)
        result = await self.session.execute(stmt)
        return result.scalars().first() is not None

    async def list_for_trade(self, trade_id: UUID) -> list[Fill]:
        """List fills for a given trade (slice trades-read-endpoints).

        :class:`Fill` carries ``order_id`` (not ``trade_id``), so we
        join through :class:`Order` to resolve the parent trade.
        Ordered ``filled_at ASC`` (chronological).
        """
        stmt = (
            select(Fill)
            .join(Order, Fill.order_id == Order.id)
            .where(Order.trade_id == trade_id)
            .order_by(Fill.filled_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def sum_quantity_for_order(self, order_id: UUID) -> Any:
        """Sum ``fills.quantity_filled`` across all fills for an order.

        Returns the SQL ``SUM(fills.quantity_filled)`` (Decimal) or 0
        if no fills are recorded yet. Used by
        :meth:`reconcile_fills_handler` to detect when the order is
        fully filled.
        """
        from sqlalchemy import func

        stmt = select(func.coalesce(func.sum(Fill.quantity_filled), 0)).where(
            Fill.order_id == order_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def latest_filled_at(self) -> datetime | None:
        """Return ``MAX(filled_at)`` across all fills, or ``None`` if empty.

        Used by :meth:`TradingService.startup_reconcile` (slice
        ``order-timeout-restart-reconcile``) to compute the ``since``
        boundary for the broker reconcile call after a daemon restart.
        Tenant filter is automatic via the slice-3 ``tenant_listener``;
        callers running outside a tenant context (e.g. system-level
        bootstrap that wants ALL tenants' last fill) should iterate
        tenants explicitly.
        """
        from sqlalchemy import func

        stmt = select(func.max(Fill.filled_at))
        result = await self.session.execute(stmt)
        return cast("datetime | None", result.scalar_one_or_none())


class EquitySnapshotRepository(BaseRepository):
    """Persistence operations for :class:`EquitySnapshot` (slice T4)."""

    async def add(self, snapshot: EquitySnapshot) -> None:
        self.session.add(snapshot)

    async def get_latest_for_tenant(self) -> EquitySnapshot | None:
        """Return the most-recent equity snapshot for the current tenant.

        Ordered ``created_at DESC LIMIT 1``. Returns ``None`` when the
        tenant has zero snapshots yet (first-boot path). Tenant filter
        is automatic via the slice-3 ``tenant_listener``.
        """
        stmt = select(EquitySnapshot).order_by(EquitySnapshot.created_at.desc()).limit(1)
        result = await self.session.execute(stmt)
        return cast("EquitySnapshot | None", result.scalars().first())

    async def get_first_snapshot_today_for_tenant(self) -> EquitySnapshot | None:
        """Return the first snapshot recorded today (UTC) for the current tenant.

        Used as the baseline for day P&L computation. Ordered
        ``created_at ASC LIMIT 1`` where ``created_at >= today_utc_midnight``.
        Returns ``None`` when no snapshot exists for today yet. Tenant
        filter is automatic via the slice-3 ``tenant_listener``.
        """
        # Explicit UTC-midnight computation — testable and avoids DB-side
        # CURRENT_DATE which is timezone-ambiguous in SQLite.
        today_utc_midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        stmt = (
            select(EquitySnapshot)
            .where(EquitySnapshot.created_at >= today_utc_midnight)
            .order_by(EquitySnapshot.created_at.asc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return cast("EquitySnapshot | None", result.scalars().first())

    async def list_for_tenant_window(self, days: int) -> list[EquitySnapshot]:
        """List equity snapshots for the current tenant within the last ``days``.

        ``created_at >= now - days*24h``, ordered ``created_at ASC``
        (chronological — matches sparkline expectation). Tenant filter
        is automatic via the slice-3 ``tenant_listener``.
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        stmt = (
            select(EquitySnapshot)
            .where(EquitySnapshot.created_at >= cutoff)
            .order_by(EquitySnapshot.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


@dataclass(frozen=True)
class DaemonStatusRow:
    """Repository row for daemon-status summary (slice ``dual-daemon-...``).

    Mirrored by ``DaemonStatusOut`` Pydantic DTO at the API layer (added
    in task 15). Kept here as a plain dataclass so the persistence layer
    does not depend on the Pydantic API DTOs.
    """

    mode: str
    enabled: bool
    ib_connected: bool
    last_heartbeat_at: datetime | None
    last_fill_at: datetime | None
    pending_proposals_count: int


class TradingModeRepository(BaseRepository):
    """Persistence operations for :class:`TenantTradingMode` +
    :class:`DaemonHeartbeat` (slice ``dual-daemon-mode-toggle-and-reconcile``).

    Both tables are composite-keyed on ``(tenant_id, mode)``; methods
    take ``tenant_id`` explicitly so the daemon can call them outside of
    a request-scope ``tenant_id_var`` (the bus listener that drives
    daemon ticks may not propagate the contextvar — daemon callers must
    pass the value they were spawned with).
    """

    async def load_trading_enabled(self, tenant_id: UUID, mode: str) -> bool:
        """Return ``enabled`` for the (tenant, mode) flag row.

        Raises :class:`LookupError` if the row is absent — every tenant
        gets seeded ``(paper, live)`` rows on migration 0026, so a
        missing row indicates an out-of-band tenant or a bug.
        """
        stmt = select(TenantTradingMode.enabled).where(
            TenantTradingMode.tenant_id == tenant_id,
            TenantTradingMode.mode == mode,
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise LookupError(
                f"tenant_trading_modes row missing for (tenant_id={tenant_id}, mode={mode}); "
                "migration 0026 should have seeded it — investigate."
            )
        return bool(row)

    async def set_trading_enabled(
        self,
        *,
        tenant_id: UUID,
        mode: str,
        enabled: bool,
        user_id: UUID | None,
        reason: str | None,
    ) -> TenantTradingMode:
        """Flip the toggle for (tenant, mode) + stamp audit columns.

        Raises :class:`LookupError` if the row is absent (same rationale
        as :meth:`load_trading_enabled`).
        """
        stmt = select(TenantTradingMode).where(
            TenantTradingMode.tenant_id == tenant_id,
            TenantTradingMode.mode == mode,
        )
        result = await self.session.execute(stmt)
        row = cast("TenantTradingMode | None", result.scalars().first())
        if row is None:
            raise LookupError(
                f"tenant_trading_modes row missing for (tenant_id={tenant_id}, mode={mode}); "
                "migration 0026 should have seeded it — investigate."
            )
        row.enabled = enabled
        row.last_toggled_at = utc_now()
        row.last_toggled_by_user_id = user_id
        row.reason = reason
        return row

    async def mark_reconcile_pending(
        self,
        *,
        tenant_id: UUID,
        mode: str,
    ) -> datetime:
        """Stamp ``tenant_trading_modes.pending_reconcile_at = now()``.

        Cross-process signal for the on-demand reconcile request: the
        API endpoint calls this, the daemon-side ``poll_for_state_changes``
        compares the column against an in-memory watermark. Returns the
        timestamp written so the API can include it in the response /
        audit log.
        """
        stmt = select(TenantTradingMode).where(
            TenantTradingMode.tenant_id == tenant_id,
            TenantTradingMode.mode == mode,
        )
        result = await self.session.execute(stmt)
        row = cast("TenantTradingMode | None", result.scalars().first())
        if row is None:
            raise LookupError(
                f"tenant_trading_modes row missing for (tenant_id={tenant_id}, mode={mode}); "
                "migration 0026 should have seeded it — investigate."
            )
        now = utc_now()
        row.pending_reconcile_at = now
        return now

    async def load_for_polling(
        self,
        *,
        tenant_id: UUID,
        mode: str,
    ) -> TenantTradingMode | None:
        """Return the full ``tenant_trading_modes`` row for poll-watermark compare.

        Daemon-side ``poll_for_state_changes`` reads
        ``last_toggled_at`` + ``pending_reconcile_at`` + ``enabled``
        from this row every heartbeat tick to detect API-side state
        changes. Returns ``None`` if the row is missing (caller can
        skip the tick rather than crash on a transient seed-gap).
        """
        stmt = select(TenantTradingMode).where(
            TenantTradingMode.tenant_id == tenant_id,
            TenantTradingMode.mode == mode,
        )
        result = await self.session.execute(stmt)
        return cast("TenantTradingMode | None", result.scalars().first())

    async def write_heartbeat(
        self,
        *,
        tenant_id: UUID,
        mode: str,
        ib_connected: bool,
    ) -> None:
        """Upsert the heartbeat row for (tenant, mode).

        First call per (tenant, mode) INSERTs; subsequent calls UPDATE
        ``last_heartbeat_at`` + ``ib_connected``. Idempotent — the
        daemon's 10s-minimum gating lives at the daemon, not here.
        """
        stmt = select(DaemonHeartbeat).where(
            DaemonHeartbeat.tenant_id == tenant_id,
            DaemonHeartbeat.mode == mode,
        )
        result = await self.session.execute(stmt)
        row = cast("DaemonHeartbeat | None", result.scalars().first())
        now = utc_now()
        if row is None:
            self.session.add(
                DaemonHeartbeat(
                    tenant_id=tenant_id,
                    mode=mode,
                    last_heartbeat_at=now,
                    ib_connected=ib_connected,
                )
            )
            return
        row.last_heartbeat_at = now
        row.ib_connected = ib_connected

    async def load_daemon_status_summary(
        self,
        tenant_id: UUID,
    ) -> list[DaemonStatusRow]:
        """Build the ``GET /api/v1/status`` payload for a tenant.

        Returns one row per mode for which a ``tenant_trading_modes``
        flag exists. Joins:

        * ``tenant_trading_modes.enabled`` (always present per seed)
        * ``daemon_heartbeats.last_heartbeat_at`` + ``ib_connected``
          (NULL when daemon never wrote a heartbeat)
        * ``fills.filled_at`` MAX via fills→orders→trades JOIN
        * ``trade_proposals`` COUNT where ``state='pending_approval'``

        ``ib_connected`` is reported as the raw row value here; the
        API route layer (task 11) maps a stale heartbeat (>30s) to
        ``ib_connected=false`` regardless of the persisted value.
        """
        flags_stmt = select(TenantTradingMode).where(TenantTradingMode.tenant_id == tenant_id)
        flags_result = await self.session.execute(flags_stmt)
        flag_rows = list(flags_result.scalars().all())

        hb_stmt = select(DaemonHeartbeat).where(DaemonHeartbeat.tenant_id == tenant_id)
        hb_result = await self.session.execute(hb_stmt)
        heartbeats = {hb.mode: hb for hb in hb_result.scalars().all()}

        rows: list[DaemonStatusRow] = []
        for flag in flag_rows:
            last_fill_stmt = (
                select(func.max(Fill.filled_at))
                .join(Order, Order.id == Fill.order_id)
                .join(Trade, Trade.id == Order.trade_id)
                .where(Trade.tenant_id == tenant_id)
                .where(Trade.mode == flag.mode)
            )
            last_fill = (await self.session.execute(last_fill_stmt)).scalar_one_or_none()

            pending_stmt = (
                select(func.count())
                .select_from(TradeProposal)
                .where(TradeProposal.tenant_id == tenant_id)
                .where(TradeProposal.mode == flag.mode)
                .where(TradeProposal.state == "pending_approval")
            )
            pending_count = (await self.session.execute(pending_stmt)).scalar_one()

            hb = heartbeats.get(flag.mode)
            rows.append(
                DaemonStatusRow(
                    mode=flag.mode,
                    enabled=bool(flag.enabled),
                    ib_connected=bool(hb.ib_connected) if hb is not None else False,
                    last_heartbeat_at=hb.last_heartbeat_at if hb is not None else None,
                    last_fill_at=last_fill,
                    pending_proposals_count=int(pending_count or 0),
                )
            )
        return rows


__all__ = [
    "DaemonStatusRow",
    "EquitySnapshotRepository",
    "FillRepository",
    "OrderRepository",
    "StrategyConfigRepository",
    "TradeProposalRepository",
    "TradeRepository",
    "TradingModeRepository",
]


# Bind the model imports to module-level so static analysis sees them as
# referenced (these are the type-binding parents for the empty-bodied
# repositories above; mypy / ruff would flag them as unused otherwise).
_ = (Fill, Order, Trade, TradeProposal, EquitySnapshot, TenantTradingMode, DaemonHeartbeat, UUID)
