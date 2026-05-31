"""Whitelist-aware L2 append-only triggers for the column-whitelisted
trading tables (audit #35): ``trades``, ``orders``, ``trade_proposals``.

Migration ``0033`` installed full-lock L2 triggers on the *pure* append-only
trading tables (``fills``, ``equity_snapshots``) and deliberately deferred the
three column-whitelisted tables, because those undergo legitimate state
transitions (order submitted→filled, trade open→closed, proposal
pending→approved) restricted to their L1 ``__append_only_mutable_columns__``
whitelist. A blanket block would refuse those legitimate UPDATEs; no block at
all (the status quo) lets raw ``session.execute(text("UPDATE trades SET
quantity = ..."))`` rewrite immutable ledger fields, violating the
"execution logs are immutable" hard rule.

This module emits the missing layer: a BEFORE UPDATE trigger that RAISEs iff a
NON-whitelisted column actually changes (``OLD.c IS NOT NEW.c``), plus a
BEFORE DELETE full lock. That mirrors the L1 ``before_flush`` listener at the
database level, keeping L1 and L2 in lockstep.

Immutability of migrations: the non-whitelisted column lists below are a
STATIC SNAPSHOT as of migration ``0035``. They are NOT derived from the ORM at
runtime — a future column addition must ship its own follow-up migration that
recreates the trigger, exactly as schema changes always do. The lockstep test
``tests/unit/persistence/test_trading_whitelist_l2_triggers.py`` asserts this
snapshot still equals ``ORM columns − whitelist`` for each table, so the drift
(new column not covered by a trigger) fails CI instead of silently shipping an
immutable field that raw SQL can rewrite.

Lives in ``migrations/`` (parallel to ``versions/``) for the same reason as
:mod:`._research_trigger_helpers`: Alembic's revision scanner treats every
module under ``versions/`` as a candidate revision.
"""

from __future__ import annotations

#: Column-whitelisted append-only trading tables covered here.
WHITELISTED_TRADING_TABLES: tuple[str, ...] = (
    "trades",
    "orders",
    "trade_proposals",
)

#: The L1 ``__append_only_mutable_columns__`` whitelist per table — duplicated
#: here purely for the human-readable RAISE message. The lockstep test asserts
#: these equal the ORM frozensets.
MUTABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "trades": (
        "state",
        "closed_at",
        "exit_reason",
        "realised_pnl",
        "journal_narrative",
        "journal_generated_at",
        "journal_model",
    ),
    "orders": (
        "state",
        "broker_order_id",
        "submitted_at",
        "acknowledged_at",
        "closed_at",
    ),
    "trade_proposals": (
        "state",
        "rejection_reason",
        "rejected_at",
        "risk_score",
        "risk_flags",
        "risk_rationale",
        "risk_generated_at",
        "risk_model",
    ),
}

#: Non-whitelisted (immutable) columns per table — the trigger RAISEs when any
#: of these actually changes. STATIC SNAPSHOT as of migration 0035 (see module
#: docstring); the lockstep test guards it against ORM drift.
NON_WHITELISTED_COLUMNS: dict[str, tuple[str, ...]] = {
    "trades": (
        "id",
        "tenant_id",
        "proposal_id",
        "symbol",
        "side",
        "quantity",
        "mode",
        "opened_at",
        "created_at",
    ),
    "orders": (
        "id",
        "tenant_id",
        "trade_id",
        "broker",
        "order_type",
        "side",
        "quantity",
        "limit_price",
        "stop_price",
        "target_price",
        "client_order_id",
        "created_at",
    ),
    "trade_proposals": (
        "id",
        "tenant_id",
        "strategy_config_id",
        "symbol",
        "side",
        "quantity",
        "entry_price_indicative",
        "stop_price",
        "target_price",
        "confidence_score",
        "reasoning",
        "research_brief_id",
        "mode",
        "correlation_id",
        "created_at",
    ),
}


def _whitelist_update_trigger(table: str) -> str:
    """SQLite BEFORE UPDATE trigger: RAISE iff a non-whitelisted column changed.

    ``IS NOT`` is null-safe in SQLite (``NULL IS NOT NULL`` → false), so a
    NULL→NULL no-op does not trip the guard — matching the L1 "actually
    changed" semantics.
    """
    changed = " OR ".join(
        f"OLD.{col} IS NOT NEW.{col}" for col in NON_WHITELISTED_COLUMNS[table]
    )
    allowed = ",".join(MUTABLE_COLUMNS[table])
    return (
        f"CREATE TRIGGER trg_{table}_no_update "
        f"BEFORE UPDATE ON {table} "
        f"FOR EACH ROW "
        f"WHEN {changed} "
        f"BEGIN "
        f"SELECT RAISE(FAIL, 'append-only: only [{allowed}] are mutable on {table}'); "
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


#: SQLite trigger DDL the migration emits + the test re-emits (create_all does
#: not model triggers).
SQLITE_TRADING_WHITELIST_TRIGGER_SQL: tuple[str, ...] = tuple(
    stmt
    for table in WHITELISTED_TRADING_TABLES
    for stmt in (_whitelist_update_trigger(table), _full_lock_delete(table))
)


def emit_postgres_trading_whitelist_triggers(op: object) -> None:
    """Emit the Postgres equivalents (RAISE EXCEPTION via plpgsql).

    Mirrors ``_trading_trigger_helpers.emit_postgres_trading_full_lock_triggers``
    but the UPDATE function guards on ``IS DISTINCT FROM`` over the
    non-whitelisted columns (the null-safe Postgres analogue of SQLite's
    ``IS NOT``). Unvalidated against a real Postgres in this MVP (SQLite is the
    dev/test DB) — kept in lockstep with the SQLite branch by construction.
    """
    execute = op.execute  # type: ignore[attr-defined]
    for table in WHITELISTED_TRADING_TABLES:
        changed = " OR ".join(
            f"OLD.{col} IS DISTINCT FROM NEW.{col}"
            for col in NON_WHITELISTED_COLUMNS[table]
        )
        allowed = ",".join(MUTABLE_COLUMNS[table])
        upd_fn = f"trg_{table}_block_nonwhitelisted_update"
        del_fn = f"trg_{table}_block_delete"
        execute(
            f"""
            CREATE OR REPLACE FUNCTION {upd_fn}() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                IF {changed} THEN
                    RAISE EXCEPTION
                        'append-only: only [{allowed}] are mutable on {table}';
                END IF;
                RETURN NEW;
            END;
            $$;
            """
        )
        execute(
            f"CREATE TRIGGER trg_{table}_no_update BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {upd_fn}();"
        )
        execute(
            f"""
            CREATE OR REPLACE FUNCTION {del_fn}() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'append-only: DELETE on {table} forbidden';
            END;
            $$;
            """
        )
        execute(
            f"CREATE TRIGGER trg_{table}_no_delete BEFORE DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {del_fn}();"
        )


__all__ = [
    "MUTABLE_COLUMNS",
    "NON_WHITELISTED_COLUMNS",
    "SQLITE_TRADING_WHITELIST_TRIGGER_SQL",
    "WHITELISTED_TRADING_TABLES",
    "emit_postgres_trading_whitelist_triggers",
]
