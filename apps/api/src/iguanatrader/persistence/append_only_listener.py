"""Global append-only listener — refuse UPDATE/DELETE on flagged tables.

Per design D3 (slice 3): two layers of defence for append-only invariant:

- **L1 (this module)**: ``before_flush`` event handler iterates ``session.dirty``
  and ``session.deleted``; raises :class:`AppendOnlyViolationError` for any
  instance whose class declares ``__tablename_is_append_only__ = True``. Catches
  all ORM-driven mutations.
- **L2 (per-table migrations)**: each migration that creates an append-only
  table also creates a BEFORE UPDATE / BEFORE DELETE trigger that issues
  ``RAISE(FAIL, ...)`` on SQLite or ``RAISE EXCEPTION`` on Postgres v1.5.
  Catches the residual case of ``session.execute(text("UPDATE ..."))`` raw SQL
  that bypasses the ORM. Slice 3 ships no append-only tables (tenants/users/
  authorized_senders are all mutable), so the trigger DDL ships with each
  consuming slice (O1, P1, etc.).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

from iguanatrader.persistence.errors import AppendOnlyViolationError


def _is_append_only(cls: type) -> bool:
    """True if ``cls`` declares ``__tablename_is_append_only__ = True``."""
    if not isinstance(cls, type):
        return False
    return bool(getattr(cls, "__tablename_is_append_only__", False))


def _block_append_only_mutations(
    session: Session,
    flush_context: Any,
    instances: Any | None = None,
) -> None:
    """``before_flush`` handler — raise on UPDATE/DELETE of append-only rows.

    Iterates ``session.dirty`` (UPDATE candidates) and ``session.deleted``
    (DELETE candidates). The ORM filters ``session.dirty`` to instances
    actually mutated since load, so this catches real UPDATEs without
    false-positives on read-only objects.
    """
    for instance in session.dirty:
        cls = type(instance)
        if _is_append_only(cls):
            raise AppendOnlyViolationError(
                f"UPDATE on {cls.__tablename__} refused: "
                "table is marked __tablename_is_append_only__ = True"
            )

    for instance in session.deleted:
        cls = type(instance)
        if _is_append_only(cls):
            raise AppendOnlyViolationError(
                f"DELETE on {cls.__tablename__} refused: "
                "table is marked __tablename_is_append_only__ = True"
            )


def register_append_only_listener() -> None:
    """Wire the append-only listener. Idempotent — safe to call from lifespan."""
    if not event.contains(Session, "before_flush", _block_append_only_mutations):
        event.listen(Session, "before_flush", _block_append_only_mutations)


def unregister_append_only_listener() -> None:
    """Remove the append-only listener. Useful for tests with custom flush behavior."""
    if event.contains(Session, "before_flush", _block_append_only_mutations):
        event.remove(Session, "before_flush", _block_append_only_mutations)


__all__ = [
    "register_append_only_listener",
    "unregister_append_only_listener",
]
