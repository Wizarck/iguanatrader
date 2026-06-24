"""ORM mappings for the ``observability`` bounded context.

Three append-only tables planted by migration ``0007_observability_tables``:

- :class:`ApiCostEvent` — every LLM call's tokens + USD cost
  (``api_cost_events``, per-tenant, FR40, NFR-O1, NFR-O7).
- :class:`ConfigChange` — diff history for tenant-level config
  mutations (``config_changes``, per-tenant, FR47).
- :class:`AuditLog` — security / ops audit trail (``audit_log``,
  per-tenant + cross-tenant ``tenant_id IS NULL`` rows for ops-global
  events per data-model §7.1, NFR-O5).

All three set ``__tablename_is_append_only__ = True`` so the slice-3
:mod:`iguanatrader.persistence.append_only_listener` rejects UPDATE /
DELETE at flush time. The L2 BEFORE-trigger DDL is added by the
migration so raw-SQL bypasses also fail.

The :class:`AuditLog` mapping declares ``__tenant_scoped__ = True`` (the
default) BUT its ``tenant_id`` column is nullable — per design D8 the
listener is taught (in slice O1's carry-forward fix to
:func:`iguanatrader.persistence.tenant_listener._inject_tenant_filter`)
to add ``WHERE tenant_id IS NULL`` when ``tenant_id_var`` is unset for
queries against this table. This matches the data-model §7.1 contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
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
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from iguanatrader.persistence.base import Base


class ApiCostEvent(Base):
    """One row per LLM call — tokens + USD cost + correlation metadata.

    Per data-model §3.5 (FR40, NFR-O1, NFR-O7):

    - ``provider`` — ``anthropic`` / ``openai`` / ``perplexity``.
    - ``model`` — the canonical model identifier (e.g. ``claude-3-5-sonnet``).
    - ``node`` — host identifier (multi-host v2).
    - ``tokens_input`` / ``tokens_output`` — non-negative ints.
    - ``cost_usd`` — :class:`Decimal` (10,4) — USD value.
    - ``cached`` — Anthropic prompt-caching hit indicator (NFR-I3); also
      ``True`` for replay-cache test runs (per design D5).
    - ``prompt_hash`` — optional SHA-256 of the rendered prompt
      (NFR-O7); MAY be ``NULL`` when a context contains PII.
    - ``metadata_json`` — free-form JSON; reserved for slice-O2 to
      record routine + step + retry-attempt nesting.
    - ``routine_run_id`` — FK to ``routine_runs`` (slice O2 lands the
      table); column is nullable + FK declared optional. Until O2
      lands, the column stays ``NULL`` for every row.
    - ``correlation_id`` — request-scope correlation (NFR-O8).
    """

    __tablename__ = "api_cost_events"
    __tablename_is_append_only__ = True

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    node: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_input: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_output: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[Any] = mapped_column(
        Numeric(precision=12, scale=6),
        nullable=False,
    )
    cached: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=false(),
    )
    prompt_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        server_default="{}",
    )
    routine_run_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )
    correlation_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    __table_args__ = (
        CheckConstraint("tokens_input >= 0", name="tokens_input_nonneg"),
        CheckConstraint("tokens_output >= 0", name="tokens_output_nonneg"),
        CheckConstraint("cost_usd >= 0", name="cost_usd_nonneg"),
    )


class ConfigChange(Base):
    """One row per tenant-level config mutation (FR47).

    Per data-model: ``entity_kind`` + ``entity_id`` identify the changed
    object (``tenant_feature_flags`` / ``strategy_config`` / etc.);
    ``before_json`` + ``after_json`` capture the diff. ``actor_user_id``
    is the user who made the change (FK to ``users``, restrict-on-delete).
    """

    __tablename__ = "config_changes"
    __tablename_is_append_only__ = True

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    actor_user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    entity_kind: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    before_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        server_default="{}",
    )
    after_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )


class AuditLog(Base):
    """Security / ops audit trail (per data-model §3.1, NFR-O5).

    ``tenant_id`` is **nullable** (per design D8): NULL means a
    cross-tenant ops-global event (gitleaks pre-commit fail,
    license-boundary check fail, scheduler-level incident).

    ``actor_kind`` is a CHECK-constrained enum:
    ``user`` / ``system`` / ``scheduler`` / ``channel``.

    ``event`` mirrors the MessageBus dot-namespaced naming convention
    (e.g. ``observability.budget.warning_threshold``,
    ``auth.login.success``).
    """

    __tablename__ = "audit_log"
    __tablename_is_append_only__ = True

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    actor_kind: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    event: Mapped[str] = mapped_column(Text, nullable=False)
    entity_kind: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    __table_args__ = (
        CheckConstraint(
            "actor_kind IN ('user','system','scheduler','channel')",
            name="actor_kind_allowed",
        ),
    )


__all__ = [
    "ApiCostEvent",
    "AuditLog",
    "ConfigChange",
]
