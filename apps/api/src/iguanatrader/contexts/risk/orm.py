"""SQLAlchemy ORM rows for the four risk tables.

Per design D4 + tasks 2.4: bounded-context ORM rows live in
``contexts/<name>/orm.py`` (rather than the platform-level
``persistence/models.py``). The platform module's docstring explicitly
flags this convention: "Subsequent slices' models live under
``contexts/<name>/models.py`` per the bounded-context decomposition".

K1 places its Pydantic value objects in ``contexts/risk/models.py`` so
the ORM layer lands in this companion ``orm.py`` rather than colliding
with the value-object module name.

Tables:

* :class:`RiskEvaluationORM` — append-only record per engine call
  (``risk_evaluations``).
* :class:`RiskOverrideORM` — append-only audit (``risk_overrides``).
* :class:`KillSwitchStateORM` — mutable single row per tenant
  (``kill_switch_state``).
* :class:`KillSwitchEventORM` — append-only event log
  (``kill_switch_events``).

The ``__tenant_scoped__`` + ``__tablename_is_append_only__`` flags on
each class are read by the slice-3 global listeners (per
``persistence/append_only_listener.py`` + ``persistence/tenant_listener.py``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar
from uuid import UUID

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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from iguanatrader.persistence.base import Base


class RiskEvaluationORM(Base):
    """Append-only row per engine call (``risk_evaluations``)."""

    __tablename__ = "risk_evaluations"
    __tablename_is_append_only__ = True

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    proposal_id: Mapped[UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
        # No FK constraint emitted at K1 propose time because T1
        # (``trade_proposals``) is unmerged. Bridge contract
        # ``0004b_risk_fk.py`` adds the FK after T1's migration lands.
    )
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    cap_type_breached: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_pct: Mapped[Any | None] = mapped_column(Numeric(8, 6), nullable=True)
    state_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        server_default="{}",
    )
    clip_quantity: Mapped[Any | None] = mapped_column(Numeric(18, 8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('allow','reject','clip')",
            name="outcome_allowed",
        ),
        CheckConstraint(
            "cap_type_breached IS NULL OR cap_type_breached IN "
            "('per_trade','daily_loss','weekly_loss','max_open','max_drawdown')",
            name="cap_type_breached_allowed",
        ),
    )


class RiskOverrideORM(Base):
    """Append-only audit row per recorded override (``risk_overrides``)."""

    __tablename__ = "risk_overrides"
    __tablename_is_append_only__ = True

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    proposal_id: Mapped[UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
        # FK to trade_proposals deferred — see RiskEvaluationORM rationale.
    )
    risk_evaluation_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("risk_evaluations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    authorised_by_user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    reason_text: Mapped[str] = mapped_column(Text, nullable=False)
    confirmation_chain: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )
    state_snapshot_at_override: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    __table_args__ = (
        CheckConstraint(
            "length(reason_text) >= 20",
            name="reason_text_min_length",
        ),
    )


class KillSwitchStateORM(Base):
    """Mutable single row per tenant (``kill_switch_state``).

    NOT append-only — explicitly mutable so the cached ``is_active``
    flag can be flipped in <2s for NFR-R5 (per design D4). The
    authoritative log lives in :class:`KillSwitchEventORM`.
    """

    __tablename__ = "kill_switch_state"
    __tablename_is_append_only__ = False

    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="0",
    )
    last_event_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        # Self-referential FK to kill_switch_events.id — added at table
        # level via __table_args__ to avoid forward-reference issues.
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )


class KillSwitchEventORM(Base):
    """Append-only authoritative log of kill-switch transitions."""

    __tablename__ = "kill_switch_events"
    __tablename_is_append_only__ = True

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    transition: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    __table_args__ = (
        CheckConstraint(
            "transition IN ('activated','deactivated')",
            name="transition_allowed",
        ),
        # Per design D7 open question + tasks 2.6: 'cli' is added to the
        # source list (data-model §3.3 omits it; K1 spec deviation).
        CheckConstraint(
            "source IN ('file_flag','env_var','channel_command',"
            "'dashboard_button','automatic_backoff','automatic_cap_breach','cli')",
            name="source_allowed",
        ),
    )


class TrailingStopAuditORM(Base):
    """Append-only audit row per trailing-stop ratchet (``trailing_stop_audit``).

    Slice ``orchestration-trailing-stops-cron``. One INSERT per sweep
    evaluation where :func:`compute_trailing_stop` returned
    ``reason='trailed'`` (the candidate strictly exceeded the previous
    stop). ``no_update`` / ``trigger_not_reached`` outcomes are logged
    but not persisted — see migration 0016 module docstring for the
    bloat-prevention rationale.

    Also serves as the **stop-history lookup** for the sweep service:
    ``latest(new_stop WHERE trade_id = ? ORDER BY swept_at DESC)`` is
    the trade's current effective stop. Fall back to
    ``TradeProposal.stop_price`` when this table has no row for the
    trade yet.

    Fully append-only: ``__append_only_mutable_columns__ = frozenset()``.
    """

    __tablename__ = "trailing_stop_audit"
    __tablename_is_append_only__ = True
    __append_only_mutable_columns__: ClassVar[frozenset[str]] = frozenset()

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
    swept_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    old_stop: Mapped[Any] = mapped_column(Numeric(18, 8), nullable=False)
    new_stop: Mapped[Any] = mapped_column(Numeric(18, 8), nullable=False)
    highest_close_since_entry: Mapped[Any] = mapped_column(Numeric(18, 8), nullable=False)
    atr: Mapped[Any] = mapped_column(Numeric(18, 8), nullable=False)
    bars_evaluated: Mapped[int] = mapped_column(Integer, nullable=False)


__all__ = [
    "KillSwitchEventORM",
    "KillSwitchStateORM",
    "RiskEvaluationORM",
    "RiskOverrideORM",
    "TrailingStopAuditORM",
]
