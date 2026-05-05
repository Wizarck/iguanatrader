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

* IDs are stored as ``CHAR(36)`` (UUID with hyphens) for SQLite parity
  with PostgreSQL ``UUID``. Application code converts to :class:`uuid.UUID`
  at the boundary when needed.
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

from sqlalchemy import CHAR, JSON, Boolean, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from iguanatrader.persistence.base import Base

if TYPE_CHECKING:
    from iguanatrader.api.auth import Role


class Tenant(Base):
    """Tenant catalogue. Cross-tenant (NOT scoped by ``tenant_id_var``)."""

    __tablename__ = "tenants"
    __tenant_scoped__ = False

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
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

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        CHAR(36),
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

    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        CHAR(36),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
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


__all__ = [
    "AuthorizedSender",
    "Tenant",
    "User",
]
