"""Per-entity repositories for the trading context.

Per design D7: each entity gets a :class:`BaseRepository` subclass.
Tenant filtering is automatic via the slice-3 ``tenant_listener`` on
every SELECT issued through the session bound to ``session_var``.

Slice T1 plants only :meth:`StrategyConfigRepository.upsert` concretely
(needed for FR2/FR3 surface area in the route stubs); other
repositories ship empty bodies and gain query helpers in slice T4.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import select

from iguanatrader.contexts.trading.models import (
    EquitySnapshot,
    Fill,
    Order,
    StrategyConfig,
    Trade,
    TradeProposal,
)
from iguanatrader.shared.contextvars import tenant_id_var
from iguanatrader.shared.kernel import BaseRepository


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

    Note: ``trade_proposals`` is strict-append-only (no
    ``__append_only_mutable_columns__`` allow-list). Rejection state is
    tracked exclusively via the :class:`ProposalRejected` bus event
    (durable through the in-process bus) plus structlog breadcrumbs;
    NO DB UPDATE is issued for state mutation. This avoids a schema
    change in T4 (proposal: T4 ships no migrations).
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
        """List open trades for the current tenant.

        ``state == 'open'``, ordered ``opened_at DESC``. Tenant filter
        is automatic via the slice-3 ``tenant_listener``.
        """
        stmt = select(Trade).where(Trade.state == "open").order_by(Trade.opened_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_state(
        self,
        trade_id: UUID,
        *,
        state: str,
        closed_at: Any | None = None,
    ) -> None:
        """Update ``trades.state`` (and optional closed_at)."""
        trade = await self.get_by_id(trade_id)
        if trade is None:
            return
        trade.state = state
        if closed_at is not None:
            trade.closed_at = closed_at


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


__all__ = [
    "EquitySnapshotRepository",
    "FillRepository",
    "OrderRepository",
    "StrategyConfigRepository",
    "TradeProposalRepository",
    "TradeRepository",
]


# Bind the model imports to module-level so static analysis sees them as
# referenced (these are the type-binding parents for the empty-bodied
# repositories above; mypy / ruff would flag them as unused otherwise).
_ = (Fill, Order, Trade, TradeProposal, EquitySnapshot, UUID)
