"""Per-entity repositories for the trading context.

Per design D7: each entity gets a :class:`BaseRepository` subclass.
Tenant filtering is automatic via the slice-3 ``tenant_listener`` on
every SELECT issued through the session bound to ``session_var``.

Slice T1 plants only :meth:`StrategyConfigRepository.upsert` concretely
(needed for FR2/FR3 surface area in the route stubs); other
repositories ship empty bodies and gain query helpers in slice T4.
"""

from __future__ import annotations

from typing import Any
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
    """Persistence operations for :class:`TradeProposal`.

    Bodies land in slice T4 (``trading-routes-and-daemon``).
    """


class TradeRepository(BaseRepository):
    """Persistence operations for :class:`Trade`.

    Bodies land in slice T4.
    """


class OrderRepository(BaseRepository):
    """Persistence operations for :class:`Order`.

    Bodies land in slice T4.
    """


class FillRepository(BaseRepository):
    """Persistence operations for :class:`Fill`.

    Bodies land in slice T4.
    """


class EquitySnapshotRepository(BaseRepository):
    """Persistence operations for :class:`EquitySnapshot`.

    Bodies land in slice T4.
    """


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
