"""L2 append-only triggers on the pure-ledger trading tables (#26)

``0004_trading_tables`` created ``fills``/``orders``/``trades``/
``trade_proposals``/``equity_snapshots`` WITHOUT the database-level
append-only triggers that the research tables got in ``0003``. So the
immutability of the execution ledger rested entirely on the ORM
``before_flush`` L1 listener — any raw ``session.execute(text("UPDATE
fills ..."))`` or out-of-ORM path could rewrite history, violating the
"execution logs are immutable" hard rule.

This installs full-lock BEFORE UPDATE/DELETE triggers on the two PURE
append-only trading tables (``fills``, ``equity_snapshots``) — neither is
ever legitimately updated, so a blanket block matches the L1 contract.

The column-whitelisted tables (``trades``, ``orders``,
``trade_proposals``) undergo legitimate state transitions and need a
WHEN-guarded, whitelist-aware trigger kept in lockstep with the L1
frozensets; that lands as the #26/#35 follow-up (the WHEN clause must
enumerate every non-whitelisted column and the Postgres branch needs a
real Postgres to validate).

Revision ID: 0033_trading_append_only_l2_triggers
Revises: 0032_risk_eval_cap_types_and_pct_width
Created at: 2026-05-31T00:00:00Z
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from iguanatrader.migrations._trading_trigger_helpers import (
    FULLY_APPEND_ONLY_TRADING_TABLES,
    SQLITE_TRADING_TRIGGER_SQL,
    emit_postgres_trading_full_lock_triggers,
)

revision: str = "0033_trading_append_only_l2_triggers"
down_revision: str | None = "0032_risk_eval_cap_types_and_pct_width"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for sql in SQLITE_TRADING_TRIGGER_SQL:
            op.execute(sql)
    elif dialect == "postgresql":
        emit_postgres_trading_full_lock_triggers(op)
    # Other dialects: L1 listener remains the guard (see migration 0003).


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    for table in FULLY_APPEND_ONLY_TRADING_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_update")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete")
        if dialect == "postgresql":
            op.execute(f"DROP FUNCTION IF EXISTS trg_{table}_block_mutation()")
