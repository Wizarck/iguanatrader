"""Postgres-only: convert SQLite-style UUID/currency columns to native types.

The historical migrations declared UUID columns as ``CHAR(36)`` and
currency columns as ``CHAR(3)`` (a SQLite-first convention — SQLite ignores
column types/lengths). On Postgres this breaks at runtime:

* the ORM binds ``uuid`` parameters, so ``WHERE tenant_id = $1::uuid``
  against a ``character(36)`` column raises ``operator does not exist:
  character = uuid``;
* IBKR reports a ``BASE`` pseudo-currency (4 chars) which overflows
  ``character(3)`` with ``StringDataRightTruncation``.

This migration converts, on Postgres only and idempotently:

* every ``character(36)`` column → ``uuid`` (dropping/recreating all FK
  constraints around the type change, since both sides must change
  together);
* every ``character(3)`` column → ``varchar(16)``.

SQLite is a no-op (its dynamic typing never had the mismatch). Downgrade
is intentionally a no-op — the native types are a strict superset and
reverting would re-introduce the runtime breakage.

Revision ID: 0037_postgres_native_types
Revises: 0036_authorized_senders_role
"""

from __future__ import annotations

from alembic import op

revision: str = "0037_postgres_native_types"
down_revision: str | None = "0036_authorized_senders_role"
branch_labels: str | None = None
depends_on: str | None = None


_CONVERT_SQL = r"""
DO $migrate$
DECLARE
    r record;
    fkdefs text[] := ARRAY[]::text[];
BEGIN
    -- Capture + drop every FK so column types can change on both sides.
    FOR r IN
        SELECT conrelid::regclass::text AS tbl, conname, pg_get_constraintdef(oid) AS def
        FROM pg_constraint WHERE contype = 'f'
    LOOP
        fkdefs := array_append(
            fkdefs,
            format('ALTER TABLE %s ADD CONSTRAINT %I %s', r.tbl, r.conname, r.def)
        );
        EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', r.tbl, r.conname);
    END LOOP;

    -- character(36) -> uuid (idempotent: only columns still character).
    FOR r IN
        SELECT table_name, column_name FROM information_schema.columns
        WHERE table_schema = 'public'
          AND data_type = 'character' AND character_maximum_length = 36
    LOOP
        EXECUTE format(
            'ALTER TABLE %I ALTER COLUMN %I TYPE uuid USING %I::uuid',
            r.table_name, r.column_name, r.column_name
        );
    END LOOP;

    -- character(3) currency codes -> varchar(16) (IBKR 'BASE' is 4 chars).
    FOR r IN
        SELECT table_name, column_name FROM information_schema.columns
        WHERE table_schema = 'public'
          AND data_type = 'character' AND character_maximum_length = 3
    LOOP
        EXECUTE format(
            'ALTER TABLE %I ALTER COLUMN %I TYPE varchar(16)',
            r.table_name, r.column_name
        );
    END LOOP;

    -- Recreate the captured FKs (now uuid<->uuid where applicable).
    IF array_length(fkdefs, 1) IS NOT NULL THEN
        FOR i IN 1 .. array_length(fkdefs, 1) LOOP
            EXECUTE fkdefs[i];
        END LOOP;
    END IF;
END
$migrate$;
"""


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(_CONVERT_SQL)


def downgrade() -> None:
    # No-op: native types are a strict superset; reverting would
    # re-introduce the char(36)=uuid / char(3) runtime breakage.
    pass
