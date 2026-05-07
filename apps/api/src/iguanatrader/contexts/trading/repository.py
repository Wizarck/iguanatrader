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
