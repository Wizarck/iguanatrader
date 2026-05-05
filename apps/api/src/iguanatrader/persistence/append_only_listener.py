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

Column-level whitelist (slice T1 ``trading-models-interfaces`` extension):
classes that need state-mutability on a small set of columns (``trades``,
``orders``) declare ``__append_only_mutable_columns__: ClassVar[frozenset[str]]``
in addition to ``__tablename_is_append_only__ = True``. The listener
permits UPDATEs whose dirty columns are a subset of the whitelist; any
column outside the whitelist trips :class:`AppendOnlyViolationError`.
DELETE is always refused (no whitelist for DELETE).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from iguanatrader.persistence.errors import AppendOnlyViolationError


def _is_append_only(cls: type) -> bool:
    """True if ``cls`` declares ``__tablename_is_append_only__ = True``."""
    if not isinstance(cls, type):
        return False
    return bool(getattr(cls, "__tablename_is_append_only__", False))


def _mutable_columns(cls: type) -> frozenset[str]:
    """Column-level whitelist for an append-only class (default: empty).

    Empty whitelist means "no UPDATE permitted on any column" — the
    classic pure-append-only contract.
    """
    raw = getattr(cls, "__append_only_mutable_columns__", None)
    if raw is None:
        return frozenset()
    return frozenset(raw)


def _dirty_column_names(instance: Any) -> set[str]:
    """Return the names of columns that have changed since load.

    Inspects the SQLAlchemy state's per-attribute history; a column is
    "dirty" when its history reports added or deleted values (i.e., the
    Python attribute differs from the loaded DB value).
    """
    state = inspect(instance)
    dirty: set[str] = set()
    for attr in state.mapper.column_attrs:
        history = state.attrs[attr.key].history
        if history.has_changes():
            dirty.add(attr.key)
    return dirty


def _block_append_only_mutations(
    session: Session,
    flush_context: Any,
    instances: Any | None = None,
) -> None:
    """``before_flush`` handler — raise on UPDATE/DELETE of append-only rows.

    Iterates ``session.dirty`` (UPDATE candidates) and ``session.deleted``
    (DELETE candidates). The ORM filters ``session.dirty`` to instances
    actually mutated since load, so this catches real UPDATEs without
    false-positives on read-only objects. For classes with a column-level
    whitelist (``__append_only_mutable_columns__``), UPDATEs whose dirty
    columns are a subset of the whitelist are permitted; out-of-whitelist
    columns raise.
    """
    for instance in session.dirty:
        cls = type(instance)
        if not _is_append_only(cls):
            continue

        whitelist = _mutable_columns(cls)
        dirty_cols = _dirty_column_names(instance)

        if not dirty_cols:
            # SQLAlchemy occasionally surfaces objects in ``session.dirty``
            # whose tracked attributes did not actually change (e.g. a
            # touched relationship whose backref was unchanged). Skip
            # these — no real UPDATE will be emitted.
            continue

        offending = dirty_cols - whitelist
        if not offending:
            continue

        raise AppendOnlyViolationError(
            f"UPDATE on {cls.__tablename__} refused: "
            f"columns {sorted(offending)!r} are not in the "
            f"append-only mutable-column whitelist {sorted(whitelist)!r}"
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
