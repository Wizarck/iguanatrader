"""Platform-level ORM models — Tenant, User, AuthorizedSender.

These three tables are cross-cutting (every bounded context joins to
``tenant_id``). Slice 3 (``persistence-tenant-enforcement``) shipped the
schema migration; slice 4 (``auth-jwt-cookie``) — the first consumer —
plants the ORM models.

Subsequent slices' models live under ``contexts/<name>/models.py`` per
the bounded-context decomposition (``research``, ``trading``, ``risk``,
``approval``, ``observability``). This file is the only platform-level
``models.py`` in the project.

Conventions:

* IDs use SQLAlchemy's :class:`Uuid` type (Python :class:`uuid.UUID` at
  the ORM boundary; SQLite stores as ``CHAR(32)`` non-hyphenated by
  default, native ``UUID`` on PostgreSQL). The slice-3 migration
  ``0001_initial_schema.py`` declared the columns as ``CHAR(36)`` —
  there's a latent ORM/migration storage-shape disagreement (ORM-driven
  ``Base.metadata.create_all`` produces ``CHAR(32)``, Alembic-driven
  produces ``CHAR(36)``); slice-3 tests rely on the ORM path so the
  pattern propagates here for consistency. Long-term fix is a slice-O1
  follow-up that aligns the migration to ``Uuid``.
* The slice-3 :func:`tenant_listener` compares
  ``instance.tenant_id != tenant_id_var.get()`` directly; both sides
  MUST be :class:`UUID` for the equality to work, hence the type choice
  here (``Mapped[str]`` would yield string-vs-UUID mismatch and trip
  :class:`TenantContextMismatchError` on every tenant-scoped insert).
* ``Tenant`` is **not** tenant-scoped (``__tenant_scoped__ = False``) — it
  is the catalogue itself. ``User`` and ``AuthorizedSender`` inherit the
  default ``__tenant_scoped__ = True`` so the slice 3 listener filters
  them by ``tenant_id_var``.
* ``role`` on ``User`` is stored as ``Text`` validated by a CHECK
  constraint at the DB level (slice 4 migration ``0002`` enforces
  ``role IN ('tenant_user','god_admin')``). The ORM keeps it as ``str``;
  the :prop:`User.role_enum` property converts to the canonical
  :class:`iguanatrader.api.auth.Role` enum.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, Uuid, func, false, true
from sqlalchemy.orm import Mapped, mapped_column

from iguanatrader.persistence.base import Base

if TYPE_CHECKING:
    from iguanatrader.api.auth import Role


class Tenant(Base):
    """Tenant catalogue. Cross-tenant (NOT scoped by ``tenant_id_var``)."""

    __tablename__ = "tenants"
    __tenant_scoped__ = False

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    feature_flags: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        server_default="{}",
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
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class User(Base):
    """Platform user. Tenant-scoped via ``tenant_id``.

    In MVP/v2 single-seat-per-tenant (per ``docs/personas-jtbd.md``
    §RBAC Matrix), each tenant has exactly one ``User`` whose
    ``role = 'tenant_user'``. ``god_admin`` is the platform-level role
    reserved for cross-tenant operators; in MVP no User row carries
    ``role = 'god_admin'`` (god-admin auth is via separate path — CLI /
    env-based, not exposed via ``/api/v1/auth/login``).
    """

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
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
    # Added 2026-05-13 by slice ``auth-change-password``. When True, the
    # ``must_change_password`` middleware gates every route except the
    # change-password / logout / me allow-list until the user rotates
    # the password. Used by admin-issued provisional credentials and the
    # future ``auth-forgot-password-flow`` slice.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=false(),
        default=False,
    )
    # NULL until the first successful password write (the bootstrap path
    # plants users without a baseline). Set via ``func.now()`` on every
    # subsequent rotation — see the change-password route + the gotcha
    # in ``apps/api/src/iguanatrader/api/routes/auth.py``.
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # Added 2026-05-13 by slice ``auth-forgot-password-flow``. Opt-in
    # recovery channels: the forgot-password endpoint fans the temporary
    # credential out to whichever ones the operator set. NULL means "do
    # not fan to this channel for this user"; email is the always-on
    # channel via the NOT NULL ``email`` column above.
    telegram_chat_id: Mapped[str | None] = mapped_column(
        String(length=64),
        nullable=True,
    )
    whatsapp_phone: Mapped[str | None] = mapped_column(
        String(length=32),
        nullable=True,
    )

    @property
    def role_enum(self) -> Role:
        """Resolve :attr:`role` to the canonical enum."""
        from iguanatrader.api.auth import Role  # local import: avoid cycle

        return Role(self.role)


class AuthorizedSender(Base):
    """Whitelisted external sender per channel (Telegram, WhatsApp).

    Tenant-scoped. Only senders matching ``(tenant_id, channel,
    external_id)`` and ``enabled=True`` may invoke approval-channel
    commands. Slice P1 wires the enforcement; slice 4 is responsible
    only for the ORM model used by future repositories.
    """

    __tablename__ = "authorized_senders"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=true(),
    )
    #: Privilege facet for bot channels (slice ``mcp-hitl-approvals`` — the
    #: deferred "slice O1 follow-up" noted on
    #: :class:`~iguanatrader.contexts.approval.channels.types.IncomingCommand`).
    #: ``'owner'`` is the tenant operator responsible for its trading; the
    #: MCP adapter maps ``owner -> IncomingCommand.role='admin'`` so the
    #: existing per-command ``required_role`` gate enforces owner-only
    #: privileged actions. Defaults to ``'user'`` (deny-by-default).
    role: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default="user",
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


__all__ = [
    "AuthorizedSender",
    "Tenant",
    "User",
]
