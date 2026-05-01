"""DDD shared-kernel building blocks: :class:`BaseRepository`.

Per design decision D2 (slice 2 ``shared-primitives``):

* The session lives in :data:`session_var` (a :class:`ContextVar`),
  populated by the request-scoped session factory in slice 5
  (``api-foundation-rfc7807``).
* :class:`BaseRepository` reads :data:`session_var` lazily — the
  constructor takes no session argument. Domain code thus never
  threads sessions through call stacks.
* Reading an unset session raises :class:`LookupError`, signalling
  that the call happened outside a request scope (programmer error).

Concrete repositories under ``contexts/<bounded_context>/repository.py``
inherit from :class:`BaseRepository` and add the SQLAlchemy ORM logic
in slice 3 + later. This slice only plants the kernel.
"""

from __future__ import annotations

from typing import Any

from iguanatrader.shared.contextvars import session_var


class BaseRepository:
    """Common base for domain repositories that read their session from
    :data:`iguanatrader.shared.contextvars.session_var`.

    The class itself is intentionally minimal: subclasses may use
    :attr:`session` (or :meth:`_session`) to access the SQLAlchemy
    AsyncSession bound to the current request / job context.
    """

    @property
    def session(self) -> Any:
        """Resolve the current async session from :data:`session_var`.

        Raises :class:`LookupError` if no session is bound to the
        current async context — which is always a programmer error
        (running domain code outside a request scope).

        Type is widened to :class:`Any` because slice 2 cannot depend
        on SQLAlchemy. Slice 3 (``persistence-tenant-enforcement``)
        refines the annotation when ``AsyncSession`` becomes a real
        runtime dependency.
        """
        sess = session_var.get()
        if sess is None:
            raise LookupError(
                "session_var is not set in the current async context. "
                "BaseRepository must be used inside a request scope or "
                "inside `with_session_context(...)` / similar."
            )
        return sess


__all__ = ["BaseRepository"]
