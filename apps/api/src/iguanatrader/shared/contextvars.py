"""Per-task context variables: tenant scope + database session.

Per design decision D2 (slice 2 ``shared-primitives``):

* :data:`tenant_id_var` — populated by the auth dependency in slice 4
  (``auth-jwt-cookie``) and read by the SQLAlchemy event listener in
  slice 3 (``persistence-tenant-enforcement``) to inject
  ``WHERE tenant_id = :ctx_tenant`` into every query against tenant-
  scoped tables.
* :data:`session_var` — populated by the FastAPI request-scoped session
  factory in slice 5; read by :class:`iguanatrader.shared.kernel.BaseRepository`
  so domain code never has to thread sessions through call stacks.

Both are :class:`contextvars.ContextVar` instances, which propagate
naturally across ``await`` points in asyncio without thread-local hacks.

Helpers:

* :func:`with_tenant_context` — async context manager that sets and
  cleanly resets :data:`tenant_id_var`. Use this in tests, in scheduled
  jobs that act on behalf of a tenant, and in any code path that runs
  outside the request lifecycle.
* :func:`propagate_tenant_to` — helper that snapshots the current
  context (including ``tenant_id_var`` + ``session_var``) and runs an
  arbitrary coroutine inside it. Useful when spawning
  :func:`asyncio.create_task` jobs that would otherwise inherit only the
  default context.
"""

from __future__ import annotations

import asyncio
import contextvars
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from typing import Any, TypeVar
from uuid import UUID

# NOTE on session typing: slice 2 must NOT depend on SQLAlchemy. We declare
# ``session_var`` as ``ContextVar[Any | None]`` here; slice 3
# (``persistence-tenant-enforcement``) refines the annotation to
# ``ContextVar[AsyncSession | None]`` when it introduces the real SQLAlchemy
# session factory and wires the tenant listener. Until then, consumers of
# ``session_var`` SHOULD treat the value as opaque.

T = TypeVar("T")

#: Per-task tenant identifier. Default ``None`` means "no tenant scope" —
#: read paths SHOULD treat ``None`` as a programming error (cross-tenant
#: leak) unless they are explicitly tenant-agnostic.
tenant_id_var: contextvars.ContextVar[UUID | None] = contextvars.ContextVar(
    "tenant_id_var",
    default=None,
)

#: Per-task database session. Default ``None`` means no session has been
#: bound; :class:`iguanatrader.shared.kernel.BaseRepository` raises
#: :class:`LookupError` in that case. Typed ``Any`` here so slice 2 does
#: not depend on SQLAlchemy; slice 3 refines the annotation when it
#: introduces ``AsyncSession``.
session_var: contextvars.ContextVar[Any | None] = contextvars.ContextVar(
    "session_var",
    default=None,
)


@asynccontextmanager
async def with_tenant_context(tenant_id: UUID | None) -> AsyncIterator[None]:
    """Set :data:`tenant_id_var` for the duration of the ``async with`` block.

    Restores the previous value (whatever it was — ``None``, another
    UUID, …) on exit, even if the block raises.
    """
    token = tenant_id_var.set(tenant_id)
    try:
        yield
    finally:
        tenant_id_var.reset(token)


def propagate_tenant_to(coro: Coroutine[Any, Any, T]) -> asyncio.Task[T]:
    """Spawn ``coro`` as an :class:`asyncio.Task` carrying the current context.

    Wraps :func:`asyncio.create_task` so that ``tenant_id_var`` (and any
    other ContextVar set in the current task) is visible inside the new
    task. By default ``create_task`` already copies the current context,
    but this helper documents the intent at the call site and gives us a
    single place to evolve the policy if needed.
    """
    return asyncio.create_task(coro, context=contextvars.copy_context())


__all__ = [
    "propagate_tenant_to",
    "session_var",
    "tenant_id_var",
    "with_tenant_context",
]
