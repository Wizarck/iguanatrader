"""SQLAlchemy ORM models for the approval bounded context.

Per slice P1 design D5: both tables are append-only — they register
``__tablename_is_append_only__ = True`` so the slice-3
:func:`register_append_only_listener` rejects UPDATE/DELETE at flush
time. Migration 0006 also installs BEFORE UPDATE / BEFORE DELETE
triggers as L2 defense (catches raw SQL bypass).

Schema mirrors ``docs/data-model.md`` §3.4 verbatim:

* :class:`ApprovalRequest` — one row per fan-out attempt; expires after
  ``timeout_seconds`` if no decision is recorded.
* :class:`ApprovalDecision` — exactly one row per request_id (UNIQUE
  constraint). First-decision-wins idempotency per design D4 / FR48.

Cross-slice notes:

* The ``proposal_id`` foreign key targets ``trade_proposals(id)`` which
  is owned by slice T1 (Wave 2). The migration declares the FK by
  textual reference; the ORM model carries the column as a bare
  :class:`UUID` without a relationship attribute (no Python-level
  coupling to T1 yet). T1 + P1 land in the same wave; merge order
  T1 → P1 ensures the table exists at upgrade time.
* The ``decided_by_user_id`` + ``decided_by_sender_id`` foreign keys
  target ``users`` + ``authorized_senders`` from slice 3's initial
  schema; both are present.
* Tenant scoping is the project default (``__tenant_scoped__ = True``);
  the slice-3 listener auto-stamps ``tenant_id_var`` on insert and
  filters on read.

Both classes set ``__tenant_scoped__ = True`` (the project default) so
the slice-3 listener stamps + filters by ``tenant_id_var``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from iguanatrader.persistence.base import Base


class ApprovalRequest(Base):
    """One fan-out of an approval question to one or more channels.

    Append-only — registered with the slice-3 ``append_only_listener``.
    The lifecycle is "INSERT once, never modified". Decisions arrive as
    separate :class:`ApprovalDecision` rows joined via ``request_id``.
    """

    __tablename__ = "approval_requests"
    __tablename_is_append_only__ = True

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    #: FK to T1's ``trade_proposals(id)``. NULL for ``action_type='exit'``
    #: rows (an exit-approval acts on a ``trade_id``, not a proposal); the FK
    #: still constrains non-null values for the entry flow (migration 0039).
    proposal_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("trade_proposals.id", ondelete="RESTRICT"),
        nullable=True,
    )
    #: WS-5 PR-B discriminator: ``'entry'`` (open a position — the existing
    #: granted-bridge → ``ProposalApproved`` path) or ``'exit'`` (close an open
    #: trade — granted-bridge → ``CloseTradeRequested``). The granted bridge is
    #: FAIL-CLOSED on this: only ``'entry'`` fires a buy, only ``'exit'`` fires
    #: a close, anything else does neither. Server default backfills legacy
    #: rows to ``'entry'``.
    action_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="entry",
    )
    #: The open trade an exit-approval acts on; NULL for entry rows.
    #: App-enforced (no DB FK) so 0039 stays a fast ADD COLUMN on the live
    #: daemon — the urgent-exit advisor validates the trade before raising.
    trade_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )
    #: JSON list of channel kinds — values from
    #: ``{"telegram", "whatsapp", "dashboard"}``. Stored as JSON for
    #: flexibility (FR32 fan-out targets are per-tenant configurable).
    delivered_to_channels: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
    )
    timeout_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    #: Per-channel delivery failure log (FR32 fan-out — per-channel
    #: failure isolation). Optional; absent for pre-failure rows.
    delivery_failures: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "timeout_seconds > 0",
            name="ck_approval_requests_timeout_positive",
        ),
    )


class ApprovalDecision(Base):
    """Append-only audit row for a single approval outcome.

    Exactly one row per ``request_id`` (UNIQUE constraint). First INSERT
    wins; subsequent attempts raise :class:`IntegrityError` which the
    service maps to :class:`ApprovalAlreadyDecidedError` (HTTP 409).

    Outcome semantics (per data-model §3.4):

    * ``granted`` / ``rejected`` — user decision via Telegram, WhatsApp,
      or dashboard.
    * ``timeout`` — sweeper-recorded; ``decided_via_channel='timeout'``;
      both ``decided_by_*`` columns NULL.
    """

    __tablename__ = "approval_decisions"
    __tablename_is_append_only__ = True

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    request_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("approval_requests.id", ondelete="RESTRICT"),
        nullable=False,
    )
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    decided_via_channel: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    decided_by_sender_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("authorized_senders.id", ondelete="RESTRICT"),
        nullable=True,
    )
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    __table_args__ = (
        UniqueConstraint(
            "request_id",
            name="uq_approval_decisions_request_id",
        ),
        CheckConstraint(
            "outcome IN ('granted','rejected','timeout')",
            name="ck_approval_decisions_outcome_allowed",
        ),
        CheckConstraint(
            "decided_via_channel IN ('telegram','whatsapp','dashboard','timeout','system')",
            name="ck_approval_decisions_channel_allowed",
        ),
        CheckConstraint(
            "latency_ms >= 0",
            name="ck_approval_decisions_latency_nonneg",
        ),
    )


__all__ = [
    "ApprovalDecision",
    "ApprovalRequest",
]
