"""L2 append-only trigger SQL for the pure-ledger trading tables (#26).

Mirrors :mod:`iguanatrader.migrations._research_trigger_helpers`: the
``before_flush`` L1 listener only guards writes that go THROUGH the ORM,
so raw ``session.execute(text("UPDATE fills ..."))`` (or any out-of-ORM
path) could silently mutate the immutable execution ledger. These L2
triggers are the database-level backstop.

Scope here is the two **pure** append-only trading tables — ``fills`` and
``equity_snapshots`` — which declare ``__tablename_is_append_only__`` with
NO ``__append_only_mutable_columns__`` whitelist, i.e. *no* UPDATE is ever
legitimate. They get a simple full-lock (block all UPDATE + DELETE),
byte-for-byte the same shape as ``_research_trigger_helpers._full_lock_*``.

The column-whitelisted tables (``trades``, ``orders``,
``trade_proposals``) undergo legitimate state transitions (order
submitted→filled, trade open→closed) restricted to their L1 whitelist, so
they need a WHEN-guarded trigger that enumerates every non-whitelisted
column and stays in lockstep with the L1 frozenset. That generator +
its Postgres branch are tracked as the #26/#35 follow-up; they are NOT
emitted here because a wrong WHEN clause on the live trade ledger would
either block legitimate transitions or allow forbidden mutations, and the
Postgres path needs a real Postgres to validate.
"""

from __future__ import annotations

#: Pure append-only trading tables — any UPDATE or DELETE is a violation.
FULLY_APPEND_ONLY_TRADING_TABLES: tuple[str, ...] = (
    "fills",
    "equity_snapshots",
)


def _full_lock_update(table: str) -> str:
    return (
        f"CREATE TRIGGER trg_{table}_no_update "
        f"BEFORE UPDATE ON {table} "
        f"FOR EACH ROW BEGIN "
        f"SELECT RAISE(FAIL, 'append-only: UPDATE on {table} forbidden'); "
        f"END"
    )


def _full_lock_delete(table: str) -> str:
    return (
        f"CREATE TRIGGER trg_{table}_no_delete "
        f"BEFORE DELETE ON {table} "
        f"FOR EACH ROW BEGIN "
        f"SELECT RAISE(FAIL, 'append-only: DELETE on {table} forbidden'); "
        f"END"
    )


#: SQLite trigger DDL the migration emits + test conftests re-emit (since
#: ``Base.metadata.create_all`` does not model triggers).
SQLITE_TRADING_TRIGGER_SQL: tuple[str, ...] = tuple(
    stmt
    for table in FULLY_APPEND_ONLY_TRADING_TABLES
    for stmt in (_full_lock_update(table), _full_lock_delete(table))
)


def emit_postgres_trading_full_lock_triggers(op: object) -> None:
    """Emit the Postgres equivalents (RAISE EXCEPTION via plpgsql).

    Mirrors ``0003_research_tables._emit_postgres_full_lock_triggers``.
    Takes the Alembic ``op`` module so this helper stays import-light.
    """
    execute = op.execute  # type: ignore[attr-defined]
    for table in FULLY_APPEND_ONLY_TRADING_TABLES:
        fn_name = f"trg_{table}_block_mutation"
        execute(
            f"""
            CREATE OR REPLACE FUNCTION {fn_name}() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'append-only: % on {table} forbidden', TG_OP;
            END;
            $$;
            """
        )
        execute(
            f"CREATE TRIGGER trg_{table}_no_update BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {fn_name}();"
        )
        execute(
            f"CREATE TRIGGER trg_{table}_no_delete BEFORE DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {fn_name}();"
        )


__all__ = [
    "FULLY_APPEND_ONLY_TRADING_TABLES",
    "SQLITE_TRADING_TRIGGER_SQL",
    "emit_postgres_trading_full_lock_triggers",
]
