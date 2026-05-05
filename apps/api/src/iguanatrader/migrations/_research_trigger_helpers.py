"""Trigger SQL helpers shared between migration ``0003_research_tables`` and tests.

Test conftest fixtures use ``Base.metadata.create_all`` to materialise
schema (faster than running the full Alembic migration chain), but the
L2 BEFORE UPDATE/DELETE triggers are NOT emitted by ``create_all`` —
SQLAlchemy doesn't model triggers natively. So we factor the trigger
DDL into this helper module and:

* The migration file (``versions/0003_research_tables.py``) imports +
  emits these in ``upgrade()`` for the SQLite branch.
* Test conftests import + execute these against the test session so the
  L2 triggers fire identically in tests.

Postgres v1.5 will need its own helper module mirroring this one;
keeping the SQLite path here matches the MVP DB.

NB: this module lives in ``migrations/`` (parallel to ``versions/``)
rather than under ``versions/`` because Alembic's revision scanner
treats EVERY module under ``versions/`` as a candidate revision and
fails on a module without a ``revision = "..."`` global. The leading-
underscore name documents implementation-detail status.
"""

from __future__ import annotations

#: Tables whose mutation is fully blocked (no narrow exception).
FULLY_APPEND_ONLY_TABLES: tuple[str, ...] = (
    "research_briefs",
    "corporate_events",
    "analyst_ratings",
)

#: Columns of ``research_facts`` other than ``recorded_to`` — used by the
#: narrow-exception trigger to assert nothing else changed.
_RESEARCH_FACTS_NON_RECORDED_TO_COLUMNS: tuple[str, ...] = (
    "id",
    "tenant_id",
    "source_id",
    "symbol_universe_id",
    "fact_kind",
    "value_numeric",
    "value_text",
    "value_jsonb",
    "unit",
    "currency",
    "effective_from",
    "effective_to",
    "recorded_from",
    "source_url",
    "retrieval_method",
    "retrieved_at",
    "raw_payload_inline",
    "raw_payload_path",
    "raw_payload_sha256",
    "raw_payload_size_bytes",
    "confidence",
    "metadata",
    "created_at",
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


def _research_facts_update_trigger() -> str:
    other_columns_changed = " OR ".join(
        f"OLD.{col} IS NOT NEW.{col}"
        for col in _RESEARCH_FACTS_NON_RECORDED_TO_COLUMNS
    )
    return (
        "CREATE TRIGGER trg_research_facts_no_update "
        "BEFORE UPDATE ON research_facts "
        "FOR EACH ROW "
        "WHEN "
        "NOT (OLD.recorded_to IS NULL AND NEW.recorded_to IS NOT NULL) "
        f"OR ({other_columns_changed}) "
        "BEGIN "
        "SELECT RAISE(FAIL, 'append-only: only recorded_to NULL->ts supersession permitted on research_facts'); "
        "END"
    )


def _research_facts_delete_trigger() -> str:
    return (
        "CREATE TRIGGER trg_research_facts_no_delete "
        "BEFORE DELETE ON research_facts "
        "FOR EACH ROW BEGIN "
        "SELECT RAISE(FAIL, 'append-only: DELETE on research_facts forbidden'); "
        "END"
    )


#: Concatenated SQLite trigger DDL the migration emits + tests re-emit.
#: Order: full-lock triggers for the three "no exception" tables, then
#: research_facts narrow-exception triggers.
SQLITE_TRIGGER_SQL: tuple[str, ...] = (
    *(stmt for table in FULLY_APPEND_ONLY_TABLES for stmt in (_full_lock_update(table), _full_lock_delete(table))),
    _research_facts_update_trigger(),
    _research_facts_delete_trigger(),
)


__all__ = [
    "FULLY_APPEND_ONLY_TABLES",
    "SQLITE_TRIGGER_SQL",
]
