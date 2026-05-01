"""Persistence layer — SQLAlchemy 2.x async + Alembic + tenant/append-only listeners.

Public API:

- :class:`Base` and :data:`metadata` — declarative base with project naming convention.
- :func:`engine_factory`, :func:`session_factory` — pure factories for AsyncEngine
  and async_sessionmaker (no module-level state).
- :func:`register_global_listeners` — single boot entry point that wires the
  tenant + append-only listeners; call it from FastAPI lifespan in slice 5.
- :func:`verify_json1_extension` — boot-time JSON1 verification for SQLite.
- Error classes: :class:`TenantContextMissingError`, :class:`TenantContextMismatchError`,
  :class:`AppendOnlyViolationError`, :class:`JSON1NotAvailableError`.
"""

from __future__ import annotations

from iguanatrader.persistence.append_only_listener import (
    register_append_only_listener,
    unregister_append_only_listener,
)
from iguanatrader.persistence.base import Base, NAMING_CONVENTION, metadata
from iguanatrader.persistence.errors import (
    AppendOnlyViolationError,
    JSON1NotAvailableError,
    TenantContextMismatchError,
    TenantContextMissingError,
)
from iguanatrader.persistence.json1_check import verify_json1_extension
from iguanatrader.persistence.session import (
    AsyncEngine,
    AsyncSession,
    engine_factory,
    session_factory,
)
from iguanatrader.persistence.tenant_listener import (
    register_tenant_listeners,
    unregister_tenant_listeners,
)


def register_global_listeners() -> None:
    """Wire all global persistence listeners. Idempotent.

    Call this once from the FastAPI lifespan in slice 5 (``api-foundation-rfc7807``)
    or once from the CLI entrypoint in slice T4 (``trading-routes-and-daemon``).
    Order matters only insofar as both listeners are eventually registered; the
    handlers are independent within a single ``before_flush`` event because each
    iterates a different attribute of the session (``new`` vs ``dirty``+``deleted``).
    """
    register_tenant_listeners()
    register_append_only_listener()


def unregister_global_listeners() -> None:
    """Remove all global persistence listeners. Useful for tests."""
    unregister_append_only_listener()
    unregister_tenant_listeners()


__all__ = [
    "AppendOnlyViolationError",
    "AsyncEngine",
    "AsyncSession",
    "Base",
    "JSON1NotAvailableError",
    "NAMING_CONVENTION",
    "TenantContextMismatchError",
    "TenantContextMissingError",
    "engine_factory",
    "metadata",
    "register_append_only_listener",
    "register_global_listeners",
    "register_tenant_listeners",
    "session_factory",
    "unregister_append_only_listener",
    "unregister_global_listeners",
    "unregister_tenant_listeners",
    "verify_json1_extension",
]
