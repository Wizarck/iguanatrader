"""Trading-context ORM models — 6 tables per ``docs/data-model.md §3.2``.

Tables:

* :class:`StrategyConfig` (mutable; FR1-FR5).
* :class:`TradeProposal` (append-only; FR11; cross-slice FK to
  ``research_briefs`` lands in slice R1's migration ``0002``).
* :class:`Trade` (column-level whitelist — only ``state`` + ``closed_at``
  mutable post-INSERT).
* :class:`Order` (column-level whitelist — broker-side fields settable
  on confirm).
* :class:`Fill` (pure append-only).
* :class:`EquitySnapshot` (pure append-only).

Append-only enforcement is centralised in
:mod:`iguanatrader.persistence.append_only_listener` (slice 3). Models
declare ``__tablename_is_append_only__ = True`` and (where applicable)
``__append_only_mutable_columns__: ClassVar[frozenset[str]]``; the
listener does the rest.

All tables inherit ``__tenant_scoped__ = True`` (default) — the slice-3
``tenant_listener`` injects ``WHERE tenant_id = :ctx_tenant`` on every
SELECT and stamps the column on every INSERT.

UUID storage shape: same Latent ORM/migration disagreement called out in
:mod:`iguanatrader.persistence.models` — ORM-driven ``create_all``
produces ``CHAR(32)`` non-hyphenated; Alembic emits ``CHAR(36)``. We
follow the platform-models pattern (``Uuid`` at the Mapped layer) for
consistency. Slice O1 will align the migration / ORM storage shapes
project-wide.

Money columns use ``Numeric(18, 8)`` per data-model §3.2 (8 decimal
places covers crypto + FX + equity tick sizes without IEEE-754 drift).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar
from uuid import UUID

import structlog
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    Uuid,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from iguanatrader.persistence.base import Base

log = structlog.get_logger("iguanatrader.contexts.trading.models")


class StrategyConfig(Base):
    """Per-tenant per-symbol strategy configuration (FR1-FR5).

    Mutable: every UPDATE bumps :attr:`version` and emits the
    structlog event ``trading.config.changed``. Slice O1 will wire the
    ``config_changes`` row insert via a SQLAlchemy event hook; slice T1
    plants only the version-bump + log breadcrumb.
    """

    __tablename__ = "strategy_configs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    strategy_kind: Mapped[str] = mapped_column(Text, nullable=False)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="1",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="1",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )


class TradeProposal(Base):
    """Strategy-emitted trade proposal (append-only; FR11).

    Carries structured reasoning + (post-R5) the bitemporal
    ``research_brief_id`` that informed the proposal. The FK target is
    nullable because proposals generated before the research domain is
    operational don't reference a brief; once R5 lands the synthesizer
    populates the column on every new row.
    """

    __tablename__ = "trade_proposals"
    __tablename_is_append_only__: ClassVar[bool] = True

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    strategy_config_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("strategy_configs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Any] = mapped_column(Numeric(18, 8), nullable=False)
    entry_price_indicative: Mapped[Any] = mapped_column(Numeric(18, 8), nullable=False)
    stop_price: Mapped[Any] = mapped_column(Numeric(18, 8), nullable=False)
    confidence_score: Mapped[Any | None] = mapped_column(Numeric(5, 4), nullable=True)
    reasoning: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    research_brief_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        # FK target lives in slice R1's migration ``0002_research_tables``
        # (table ``research_briefs``); the merge order is documented in
        # the design doc §D5. We deliberately do NOT declare an ORM-level
        # ``ForeignKey("research_briefs.id", ...)`` here because the
        # ``research_briefs`` table is owned by R1 and the bounded
        # context's ORM does not yet have a sibling :class:`ResearchBrief`
        # model — ``Base.metadata.create_all`` would fail to resolve the
        # FK at test time. The FK is declared in the migration
        # ``0003_trading_tables.py`` with ``ondelete='RESTRICT'`` so the
        # DB-level enforcement is intact post-rebase on R1.
        nullable=True,
    )
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )


class Trade(Base):
    """Lifecycle row for a concrete trade (FR46).

    Column-level whitelist for the slice-3 append-only listener: only
    ``state`` and ``closed_at`` are mutable post-INSERT. Justification
    lives in ``docs/data-model.md §3.2 trades note`` — querying
    ``WHERE state = 'open'`` must be sub-millisecond, so state is
    materialised on the row instead of derived from an event log.
    """

    __tablename__ = "trades"
    __tablename_is_append_only__: ClassVar[bool] = True
    __append_only_mutable_columns__: ClassVar[frozenset[str]] = frozenset(
        {"state", "closed_at"}
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    proposal_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("trade_proposals.id", ondelete="RESTRICT"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Any] = mapped_column(Numeric(18, 8), nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )


class Order(Base):
    """Broker-side order row (FR14, FR15).

    Column-level whitelist: ``state`` + the broker-confirm timestamps
    + ``broker_order_id`` are settable after INSERT (the broker's
    ack happens asynchronously; INSERT happens at ``place_order`` call
    site).
    """

    __tablename__ = "orders"
    __tablename_is_append_only__: ClassVar[bool] = True
    __append_only_mutable_columns__: ClassVar[frozenset[str]] = frozenset(
        {
            "state",
            "broker_order_id",
            "submitted_at",
            "acknowledged_at",
            "closed_at",
        }
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    trade_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("trades.id", ondelete="RESTRICT"),
        nullable=False,
    )
    broker: Mapped[str] = mapped_column(Text, nullable=False)
    broker_order_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_type: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Any] = mapped_column(Numeric(18, 8), nullable=False)
    limit_price: Mapped[Any | None] = mapped_column(Numeric(18, 8), nullable=True)
    stop_price: Mapped[Any | None] = mapped_column(Numeric(18, 8), nullable=True)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )


class Fill(Base):
    """Broker-reported fill (pure append-only).

    Multiple fills per order are possible (partial fills). The
    ``broker_fill_id`` is the broker's stable identifier — used for
    idempotency on reconciliation.
    """

    __tablename__ = "fills"
    __tablename_is_append_only__: ClassVar[bool] = True

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    order_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity_filled: Mapped[Any] = mapped_column(Numeric(18, 8), nullable=False)
    fill_price: Mapped[Any] = mapped_column(Numeric(18, 8), nullable=False)
    commission: Mapped[Any] = mapped_column(
        Numeric(18, 8),
        nullable=False,
        server_default="0",
    )
    commission_currency: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="'USD'",
    )
    filled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    broker_fill_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )


class EquitySnapshot(Base):
    """Account equity snapshot (pure append-only).

    Drives the equity-curve dashboard + ``/sse/equity`` push (slice T4 +
    W1). Per data-model §7.2 update the ``snapshot_kind`` enum is
    ``('event','minute','daily')`` (the §3.2 ``'tick'`` value is
    deprecated; see ``open question`` in design doc and migration
    inline comment).
    """

    __tablename__ = "equity_snapshots"
    __tablename_is_append_only__: ClassVar[bool] = True

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    account_equity: Mapped[Any] = mapped_column(Numeric(18, 8), nullable=False)
    cash_balance: Mapped[Any] = mapped_column(Numeric(18, 8), nullable=False)
    realized_pnl_today: Mapped[Any] = mapped_column(
        Numeric(18, 8),
        nullable=False,
        server_default="0",
    )
    unrealized_pnl: Mapped[Any] = mapped_column(
        Numeric(18, 8),
        nullable=False,
        server_default="0",
    )
    currency: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="'USD'",
    )
    snapshot_kind: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )


# CHECK constraints declared at the model level so they ship via
# ``Base.metadata.create_all`` (test path) AND the migration. Migration
# names them with the project naming convention; ORM names use the same
# convention so introspection matches in both paths.
StrategyConfig.__table_args__ = ()
TradeProposal.__table_args__ = (
    CheckConstraint("side IN ('buy','sell')", name="ck_trade_proposals_side_allowed"),
    CheckConstraint(
        "mode IN ('paper','live')",
        name="ck_trade_proposals_mode_allowed",
    ),
    CheckConstraint(
        "quantity > 0",
        name="ck_trade_proposals_quantity_positive",
    ),
    CheckConstraint(
        "confidence_score IS NULL OR (confidence_score BETWEEN 0 AND 1)",
        name="ck_trade_proposals_confidence_score_range",
    ),
)
Trade.__table_args__ = (
    CheckConstraint("side IN ('buy','sell')", name="ck_trades_side_allowed"),
    CheckConstraint("mode IN ('paper','live')", name="ck_trades_mode_allowed"),
    CheckConstraint(
        "state IN ('open','closed_filled','closed_force_exit','closed_canceled')",
        name="ck_trades_state_allowed",
    ),
    CheckConstraint("quantity > 0", name="ck_trades_quantity_positive"),
)
Order.__table_args__ = (
    CheckConstraint(
        "broker IN ('ibkr','simulated')",
        name="ck_orders_broker_allowed",
    ),
    CheckConstraint(
        "order_type IN ('market','limit','stop','stop_limit')",
        name="ck_orders_order_type_allowed",
    ),
    CheckConstraint("side IN ('buy','sell')", name="ck_orders_side_allowed"),
    CheckConstraint(
        "state IN ('new','submitted','partially_filled','filled','canceled','rejected')",
        name="ck_orders_state_allowed",
    ),
    CheckConstraint("quantity > 0", name="ck_orders_quantity_positive"),
)
Fill.__table_args__ = (
    CheckConstraint(
        "quantity_filled > 0",
        name="ck_fills_quantity_filled_positive",
    ),
)
EquitySnapshot.__table_args__ = (
    CheckConstraint("mode IN ('paper','live')", name="ck_equity_snapshots_mode_allowed"),
    # Per data-model §7.2 update — drop ``'tick'`` (and ``'hourly'`` per
    # design Open Question Q3 / tasks.md 2.4); authoritative enum is
    # ``('event','minute','daily')``. Migration carries the same set.
    CheckConstraint(
        "snapshot_kind IN ('event','minute','daily')",
        name="ck_equity_snapshots_snapshot_kind_allowed",
    ),
)


# ---------------------------------------------------------------------------
# Per-class hooks — version bump + structlog breadcrumb on
# ``StrategyConfig`` UPDATE. Slice O1 wires the ``config_changes`` row
# insert; T1 plants only the bump + log so the contract is stable from
# T1 onwards.
# ---------------------------------------------------------------------------
@event.listens_for(StrategyConfig, "before_update", propagate=False)
def _strategy_config_before_update(
    mapper: Any, connection: Any, target: StrategyConfig
) -> None:
    """Bump :attr:`StrategyConfig.version` + emit ``trading.config.changed``.

    Hook is registered at module import time. The structlog event is the
    breadcrumb T4 / O1 will hang the ``config_changes`` row insert off;
    slice T1 only ships the breadcrumb.
    """
    target.version = (target.version or 0) + 1
    log.info(
        "trading.config.changed",
        strategy_config_id=str(target.id),
        strategy_kind=target.strategy_kind,
        symbol=target.symbol,
        new_version=target.version,
    )


__all__ = [
    "EquitySnapshot",
    "Fill",
    "Order",
    "StrategyConfig",
    "Trade",
    "TradeProposal",
]
