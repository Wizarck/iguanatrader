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
    UniqueConstraint,
    Uuid,
    event,
    false,
    func,
    true,
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
        server_default=true(),
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
    # ``__tablename_is_append_only__`` is declared on :class:`Base` as an
    # instance-attribute annotation; per-subclass overrides land as plain
    # class attributes (no ClassVar annotation) so mypy doesn't flag a
    # variance mismatch with the parent's declaration.
    __tablename_is_append_only__ = True
    # Slice ``dual-daemon-mode-toggle-and-reconcile``: ``state`` +
    # ``rejection_reason`` + ``rejected_at`` are mutable post-INSERT so
    # the approval-decision handlers + the drain logic can advance the
    # lifecycle. Same column-whitelist pattern that ``Trade`` already
    # uses for its close-flow columns.
    __append_only_mutable_columns__: ClassVar[frozenset[str]] = frozenset(
        {
            "state",
            "rejection_reason",
            "rejected_at",
            "risk_score",
            "risk_flags",
            "risk_rationale",
            "risk_generated_at",
            "risk_model",
        }
    )

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
    # Slice ``exit-classification-stop-hit-sweep`` (migration 0025) —
    # LLM-emitted 12-month take-profit. NULL when the prompt did not
    # commit to a target (low-confidence HOLD paths) or for legacy
    # pre-slice rows. The stop-hit sweep skips target evaluation when
    # NULL and only fires ``CloseTradeRequested(reason="target")``
    # when set + breached.
    target_price: Mapped[Any | None] = mapped_column(Numeric(18, 8), nullable=True)
    confidence_score: Mapped[Any | None] = mapped_column(Numeric(5, 4), nullable=True)
    reasoning: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    research_brief_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        # FK target lives in slice R1's migration ``0003_research_tables``
        # (table ``research_briefs``; R1 took 0003 because slice 4 had
        # already taken 0002_users_role_enum). The merge order is
        # documented in the design doc §D5. We deliberately do NOT declare
        # an ORM-level ``ForeignKey("research_briefs.id", ...)`` here
        # because the ``research_briefs`` table is owned by R1 and this
        # bounded context's ORM does not have a sibling
        # :class:`ResearchBrief` model — ``Base.metadata.create_all``
        # would fail to resolve the FK at test time. The FK is declared
        # in the migration ``0004_trading_tables.py`` with
        # ``ondelete='RESTRICT'`` so the DB-level enforcement is intact.
        nullable=True,
    )
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    # Slice ``dual-daemon-mode-toggle-and-reconcile``: proposal lifecycle
    # state — ``pending_approval`` until an approval decision lands,
    # then ``approved`` / ``rejected`` (human or daemon-drained) /
    # ``expired`` (approval timeout). Migration 0028 backfills legacy
    # rows as ``approved`` so they stay out of any toggle-off drain.
    state: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="'pending_approval'",
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_flags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    risk_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    risk_model: Mapped[str | None] = mapped_column(Text, nullable=True)


class Trade(Base):
    """Lifecycle row for a concrete trade (FR46).

    Column-level whitelist for the slice-3 append-only listener: only
    ``state`` and ``closed_at`` are mutable post-INSERT. Justification
    lives in ``docs/data-model.md §3.2 trades note`` — querying
    ``WHERE state = 'open'`` must be sub-millisecond, so state is
    materialised on the row instead of derived from an event log.
    """

    __tablename__ = "trades"
    __tablename_is_append_only__ = True
    # Slice ``trades-add-exit-and-realised-pnl-columns`` extension: the
    # close-flow service will populate ``exit_reason`` + ``realised_pnl``
    # in the same UPDATE that transitions ``state`` to a closed value;
    # both columns join the whitelist so the append-only listener
    # permits that UPDATE.
    #
    # Slice ``llm-observability-and-signals`` extension: the journal
    # endpoint adds ``journal_narrative`` + ``journal_generated_at`` +
    # ``journal_model`` so an LLM-generated post-mortem can be
    # persisted on the trade row (migration 0018).
    __append_only_mutable_columns__: ClassVar[frozenset[str]] = frozenset(
        {
            "state",
            "closed_at",
            "exit_reason",
            "realised_pnl",
            "journal_narrative",
            "journal_generated_at",
            "journal_model",
        }
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
    # Categorical close reason — one of {'stop','target','manual','expiry'}
    # enforced by ``ck_trades_exit_reason_allowed``. NULL = "unknown"
    # (legacy rows + any row still in ``state == 'open'``).
    exit_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Realised P&L at close, account currency, NUMERIC(18, 8). NULL on
    # legacy rows + open trades; risk-cap aggregations skip NULL.
    realised_pnl: Mapped[Any | None] = mapped_column(
        Numeric(18, 8),
        nullable=True,
    )
    # Slice ``llm-observability-and-signals``: LLM-generated trade
    # journal narrative (post-mortem). NULL until the journal endpoint
    # is POSTed; the endpoint short-circuits with 409 on a populated
    # row unless ``?regenerate=true`` is set.
    journal_narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    journal_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    journal_model: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    __tablename_is_append_only__ = True
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
    # Audit #6 (minimal): protective take-profit target copied from the
    # originating proposal at submit time (NULL when the proposal had no
    # target). Auditable record of the protective intent — see ``NewOrder``.
    target_price: Mapped[Any | None] = mapped_column(Numeric(18, 8), nullable=True)
    # Audit #7: deterministic caller-supplied idempotency key (see
    # ``ports.derive_client_order_id``). Persisted so a timed-out / reconnect
    # submission stays correlatable to its broker order without re-submitting.
    # UNIQUE per tenant — see ``uq_orders_tenant_client_order_id``. Immutable
    # post-INSERT (NOT on the append-only whitelist).
    client_order_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
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
    __tablename_is_append_only__ = True

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


class TenantTradingMode(Base):
    """Per-tenant per-mode trading enable flag (slice ``dual-daemon-mode-toggle-and-reconcile``).

    Mutable: toggled via ``POST /api/v1/daemons/{mode}/toggle``. The
    composite primary key ``(tenant_id, mode)`` ensures exactly one row
    per (tenant, mode) pair. Migration 0026 seeds paper-enabled + live-
    disabled for every existing tenant.

    ``ondelete=CASCADE`` on ``tenant_id`` (not the usual project
    RESTRICT) — these rows are pure config, not historical truth, so
    deleting a tenant should sweep their flags rather than block the
    delete. ``ondelete=SET NULL`` on ``last_toggled_by_user_id`` so the
    audit row survives user deletion.
    """

    __tablename__ = "tenant_trading_modes"

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    mode: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=false(),
    )
    last_toggled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    last_toggled_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Slice ``dual-daemon-...`` Phase 3.5: durable marker for the
    # cross-process reconcile request. API endpoint writes ``now()`` on
    # every request; daemon-side ``poll_for_state_changes`` compares
    # against its in-memory watermark + runs reconcile when newer.
    pending_reconcile_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class DaemonHeartbeat(Base):
    """Per-(tenant, mode) daemon liveness row (slice ``dual-daemon-mode-toggle-and-reconcile``).

    Upserted every ~10s by each running daemon with the current IBKR
    connection state. Read by ``GET /api/v1/status``; stale (>30s)
    rows surface as ``ib_connected=false``. No seed — rows appear on
    first heartbeat write per (tenant, mode).
    """

    __tablename__ = "daemon_heartbeats"

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    mode: Mapped[str] = mapped_column(Text, primary_key=True)
    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    ib_connected: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=false(),
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
    __tablename_is_append_only__ = True

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
    CheckConstraint(
        "state IN ('pending_approval','approved','rejected','expired')",
        name="ck_trade_proposals_state_allowed",
    ),
    CheckConstraint(
        "risk_score IS NULL OR (risk_score BETWEEN 0 AND 100)",
        name="ck_trade_proposals_risk_score_range",
    ),
)
Trade.__table_args__ = (
    CheckConstraint("side IN ('buy','sell')", name="ck_trades_side_allowed"),
    CheckConstraint("mode IN ('paper','live')", name="ck_trades_mode_allowed"),
    # Slice ``trade-state-machine-redesign`` (migration 0017): three-state
    # enum. ``open`` = active (pre-fill or live), ``closing`` = exit order
    # submitted, ``closed`` = terminated (``exit_reason`` records the
    # category, ``realised_pnl`` the P&L). The pre-slice four-variant
    # encoding (``closed_filled`` / ``closed_force_exit`` /
    # ``closed_canceled``) was redundant with the ``exit_reason`` column.
    CheckConstraint(
        "state IN ('open', 'closing', 'closed')",
        name="ck_trades_state_allowed",
    ),
    CheckConstraint("quantity > 0", name="ck_trades_quantity_positive"),
    # Mirrors migration ``0015_trade_exit_columns``: NULL or one of the
    # four canonical close categories. Declared at the model level so
    # ``Base.metadata.create_all`` (used by the in-memory SQLite test
    # path) ships the same constraint as the migrated DB.
    CheckConstraint(
        "exit_reason IS NULL OR exit_reason IN "
        "('stop','target','manual','expiry','ibkr_reconcile')",
        name="ck_trades_exit_reason_allowed",
    ),
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
    # Audit #7: ``timeout_pending`` is a NON-terminal state — a submission
    # that timed out may still be live at the broker, so it is held for
    # reconciliation rather than marked terminally ``rejected``.
    CheckConstraint(
        "state IN ('new','submitted','partially_filled','filled',"
        "'canceled','rejected','timeout_pending')",
        name="ck_orders_state_allowed",
    ),
    CheckConstraint("quantity > 0", name="ck_orders_quantity_positive"),
    # Audit #7: client_order_id is unique per tenant (NULLs are distinct,
    # so legacy rows without one do not collide). Guards against two orders
    # claiming the same idempotency key within a tenant.
    UniqueConstraint(
        "tenant_id",
        "client_order_id",
        name="uq_orders_tenant_client_order_id",
    ),
)
Fill.__table_args__ = (
    CheckConstraint(
        "quantity_filled > 0",
        name="ck_fills_quantity_filled_positive",
    ),
)
TenantTradingMode.__table_args__ = (
    CheckConstraint(
        "mode IN ('paper','live')",
        name="ck_tenant_trading_modes_mode_allowed",
    ),
)
DaemonHeartbeat.__table_args__ = (
    CheckConstraint(
        "mode IN ('paper','live')",
        name="ck_daemon_heartbeats_mode_allowed",
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
def _strategy_config_before_update(mapper: Any, connection: Any, target: StrategyConfig) -> None:
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
    "DaemonHeartbeat",
    "EquitySnapshot",
    "Fill",
    "Order",
    "StrategyConfig",
    "TenantTradingMode",
    "Trade",
    "TradeProposal",
]
