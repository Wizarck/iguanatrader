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

#: Per-delivery transactional-outbox buffer (audit #2/#27/#29). When a unit of
#: work runs under :func:`session_scoped_delivery` / :func:`run_in_session_scope`,
#: this holds a list; :meth:`MessageBus.publish` appends to it instead of
#: delivering immediately, and the buffered events are published only AFTER the
#: session commits. That guarantees a downstream subscriber (which reads in its
#: OWN per-delivery session) never observes a row the upstream handler has not
#: yet committed — the read-after-write race that session-per-delivery would
#: otherwise introduce at every hop. ``None`` (the default, i.e. outside a unit
#: of work) means "publish immediately" — the historical behavior.
publish_outbox_var: contextvars.ContextVar[list[Any] | None] = contextvars.ContextVar(
    "publish_outbox_var",
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


@asynccontextmanager
async def with_session_context(
    session: Any,
    tenant_id: UUID | None = None,
) -> AsyncIterator[None]:
    """Bind :data:`session_var` (and optionally :data:`tenant_id_var`) for a block.

    Both are reset to their prior values on exit, even on error. ``tenant_id``
    is left untouched when ``None`` so callers that only want to swap the
    session don't clobber an ambient tenant scope.
    """
    s_token = session_var.set(session)
    t_token = tenant_id_var.set(tenant_id) if tenant_id is not None else None
    try:
        yield
    finally:
        session_var.reset(s_token)
        if t_token is not None:
            tenant_id_var.reset(t_token)


async def run_in_session_scope(
    session_factory: Any,
    bus: Any,
    tenant_id: UUID | None,
    fn: Any,
) -> Any:
    """Run ``await fn()`` as one durable unit of work (audit #2/#27/#29).

    Opens a fresh session, binds ``session_var`` (+ ``tenant_id_var`` when
    ``tenant_id`` is given), installs a transactional outbox so any
    ``bus.publish(...)`` the work issues is BUFFERED, then **commits on success
    / rolls back on failure**. Buffered events are published to ``bus`` only
    after the commit succeeds (publish-after-commit), so downstream subscribers
    always read committed state. Returns whatever ``fn`` returns.

    This is the shared core of the bus delivery middleware
    (:func:`session_scoped_delivery`) and the daemon's per-tick cron wrapper —
    both are "run this coroutine in its own committed unit of work, then fan
    out the events it produced".
    """
    outbox: list[Any] = []
    result: Any = None
    async with session_factory() as session, with_session_context(session, tenant_id):
        token = publish_outbox_var.set(outbox)
        try:
            result = await fn()
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
        finally:
            publish_outbox_var.reset(token)
    # Session committed + closed, outbox no longer bound on this context →
    # publishing now delivers immediately (each downstream delivery opens its
    # own unit of work + outbox in turn).
    for event in outbox:
        await bus.publish(event)
    return result


def session_scoped_delivery(session_factory: Any, bus: Any) -> Any:
    """Build a :data:`MessageBus` delivery middleware that runs each handler in
    a fresh per-delivery unit of work with publish-after-commit (audit
    #2/#27/#29).

    Root cause the middleware closes: the trading daemon backed *every* bus
    worker + cron with a SINGLE long-lived :class:`AsyncSession`
    (``cli/trading.py``). Handlers only ``session.add(...)`` and never commit,
    so the durable ledger write depended on an incidental later commit; a
    rollback in one handler tore pending writes out of another; and the
    kill-switch auto-activation never committed (#27), so a crash could resume
    trading after a breach.

    For each delivery this opens a fresh session, binds ``session_var`` +
    ``tenant_id_var`` (the latter from the event's ``tenant_id`` — events carry
    it explicitly, never relying on contextvar propagation across the worker
    boundary), runs the handler, commits/rolls back at the boundary, and only
    then fans out any events the handler published. The exception is re-raised
    so the bus worker's own log-and-continue guard still records the failure
    (the rollback has already protected durability).

    ``session_factory`` is any zero-arg callable returning an async context
    manager that yields a session (e.g. an ``async_sessionmaker``). ``bus`` is
    the :class:`MessageBus` the buffered events are published to. Typed ``Any``
    so slice-2 ``shared`` does not import SQLAlchemy.
    """
    from iguanatrader.shared.messagebus import Event  # local: avoid import cycle

    async def _middleware(handler: Any, event: Event) -> None:
        tenant_id = getattr(event, "tenant_id", None)
        await run_in_session_scope(
            session_factory,
            bus,
            tenant_id,
            lambda: handler(event),
        )

    return _middleware


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
    "publish_outbox_var",
    "run_in_session_scope",
    "session_scoped_delivery",
    "session_var",
    "tenant_id_var",
    "with_session_context",
    "with_tenant_context",
]
