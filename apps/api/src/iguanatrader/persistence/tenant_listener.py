"""Global tenant-isolation listeners — auto-filter SELECTs + auto-stamp INSERTs.

Per design D1 + D2 (slice 3):

- ``do_orm_execute`` event handler walks every ORM-mapped class in the registry
  and applies :func:`with_loader_criteria` so that any tenant-scoped table
  referenced by the SELECT is filtered to the current tenant. Tables that opt
  out via ``__tenant_scoped__ = False`` (e.g. cross-tenant catalogues) are not
  filtered.
- ``before_flush`` event handler iterates ``session.new`` and stamps
  ``tenant_id`` on tenant-scoped instances. If the caller already set
  ``tenant_id`` to a value that does not match :data:`tenant_id_var`,
  :class:`TenantContextMismatchError` is raised — defence-in-depth against
  accidental cross-tenant writes.

Raw SQL via ``session.execute(text(...))`` BYPASSES this layer; raw SQL is
opt-in privilege per the ``gotchas.md`` entry. The ORM is the contract.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from iguanatrader.persistence.base import Base
from iguanatrader.persistence.errors import (
    TenantContextMismatchError,
    TenantContextMissingError,
)
from iguanatrader.shared.contextvars import tenant_id_var


def _read_tenant_or_raise() -> UUID:
    """Return current ``tenant_id_var`` or raise :class:`TenantContextMissingError`."""
    try:
        value = tenant_id_var.get()
    except LookupError:
        raise TenantContextMissingError(
            "tenant_id_var has no value in the current ContextVar chain — set it "
            "via with_tenant_context() before issuing tenant-scoped queries"
        ) from None
    if value is None:
        raise TenantContextMissingError(
            "tenant_id_var is set to None — set a real UUID via "
            "with_tenant_context() before issuing tenant-scoped queries"
        )
    return value


def _is_tenant_scoped(cls: type) -> bool:
    """True if ``cls`` is a tenant-scoped mapped class (default True per Base)."""
    if not isinstance(cls, type):
        return False
    return bool(getattr(cls, "__tenant_scoped__", True))


def _inject_tenant_filter(state: ORMExecuteState) -> None:
    """``do_orm_execute`` handler — add ``WHERE tenant_id = :current`` to SELECTs.

    Skips:
    - Non-SELECT statements (handled by ``before_flush`` for INSERTs).
    - Raw SQL via ``execute(text(...))`` (``is_orm_statement`` is False).
    - Mapped classes whose ``__tenant_scoped__`` is False.

    Applied via :func:`with_loader_criteria` for each tenant-scoped mapper in the
    registry. SQLAlchemy is a no-op for mappers not referenced in the query.
    """
    if not state.is_select or not state.is_orm_statement:
        return

    tenant = _read_tenant_or_raise()

    # SA 2.x caches statements aggressively. Lambda-form criteria can capture
    # stale tenant values across test runs because the lambda identity is
    # cached, not the closure values. Pass the SQL expression directly so the
    # tenant becomes a bind parameter per query — no closure capture.
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        if not _is_tenant_scoped(cls):
            continue
        if not hasattr(cls, "tenant_id"):
            continue
        criteria = with_loader_criteria(
            cls,
            cls.tenant_id == tenant,
            include_aliases=True,
        )
        state.statement = state.statement.options(criteria)


def _stamp_tenant_on_inserts(
    session: Session,
    flush_context: Any,
    instances: Any | None = None,
) -> None:
    """``before_flush`` handler — set ``tenant_id`` on new tenant-scoped rows.

    Two outcomes per new instance:
    - ``tenant_id`` is None → set to current ``tenant_id_var``.
    - ``tenant_id`` is set but does not match → raise :class:`TenantContextMismatchError`.

    The mismatch branch is defence-in-depth: catches code paths that received an
    attacker-controlled ``tenant_id`` and tried to write across tenant boundaries.
    """
    new_instances = list(session.new)
    if not new_instances:
        return

    tenant_seen: UUID | None = None

    for instance in new_instances:
        cls = type(instance)
        if not _is_tenant_scoped(cls):
            continue
        if not hasattr(instance, "tenant_id"):
            continue

        current = getattr(instance, "tenant_id", None)
        if current is None:
            if tenant_seen is None:
                tenant_seen = _read_tenant_or_raise()
            instance.tenant_id = tenant_seen
        else:
            if tenant_seen is None:
                tenant_seen = _read_tenant_or_raise()
            if current != tenant_seen:
                raise TenantContextMismatchError(
                    f"insert into {cls.__tablename__} carries tenant_id={current} "
                    f"but tenant_id_var is {tenant_seen}; cross-tenant writes "
                    "are blocked at flush time"
                )


def register_tenant_listeners() -> None:
    """Wire both tenant listeners. Idempotent — safe to call from FastAPI lifespan."""
    if not event.contains(Session, "do_orm_execute", _inject_tenant_filter):
        event.listen(Session, "do_orm_execute", _inject_tenant_filter)
    if not event.contains(Session, "before_flush", _stamp_tenant_on_inserts):
        event.listen(Session, "before_flush", _stamp_tenant_on_inserts)


def unregister_tenant_listeners() -> None:
    """Remove the tenant listeners. Useful for tests that want a clean session."""
    if event.contains(Session, "do_orm_execute", _inject_tenant_filter):
        event.remove(Session, "do_orm_execute", _inject_tenant_filter)
    if event.contains(Session, "before_flush", _stamp_tenant_on_inserts):
        event.remove(Session, "before_flush", _stamp_tenant_on_inserts)


__all__ = [
    "register_tenant_listeners",
    "unregister_tenant_listeners",
]
