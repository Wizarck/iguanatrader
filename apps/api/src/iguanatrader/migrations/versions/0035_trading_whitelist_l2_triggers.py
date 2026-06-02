"""whitelist-aware L2 append-only triggers on trades/orders/trade_proposals (#35)

Migration ``0033`` installed full-lock L2 triggers on the *pure* append-only
trading tables (``fills``, ``equity_snapshots``) and deferred the three
column-whitelisted tables — ``trades``, ``orders``, ``trade_proposals`` — which
undergo legitimate, whitelist-restricted state transitions. Until now their
immutability rested solely on the ORM ``before_flush`` L1 listener, so any raw
``session.execute(text("UPDATE trades SET quantity = ..."))`` could rewrite an
immutable ledger field.

This installs the missing L2 layer: a BEFORE UPDATE trigger that RAISEs iff a
NON-whitelisted column actually changes, plus a BEFORE DELETE full lock — the
database-level mirror of L1, kept in lockstep with the same column whitelist
(see :mod:`iguanatrader.migrations._trading_whitelist_trigger_helpers` and the
lockstep test).

Depends on ``0034`` because the ``orders`` trigger references the
``target_price`` + ``client_order_id`` columns that migration added.

Revision ID: 0035_trading_whitelist_l2_triggers
Revises: 0034_orders_stop_target_client_order_id
Created at: 2026-06-01T00:00:00Z
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from iguanatrader.migrations._trading_whitelist_trigger_helpers import (
    SQLITE_TRADING_WHITELIST_TRIGGER_SQL,
    WHITELISTED_TRADING_TABLES,
    emit_postgres_trading_whitelist_triggers,
)

revision: str = "0035_trading_whitelist_l2_triggers"
down_revision: str | None = "0034_orders_stop_target_client_order_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for sql in SQLITE_TRADING_WHITELIST_TRIGGER_SQL:
            op.execute(sql)
    elif dialect == "postgresql":
        emit_postgres_trading_whitelist_triggers(op)
    # Other dialects: L1 listener remains the guard (see migration 0003).


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    for table in WHITELISTED_TRADING_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_update")
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete")
        if dialect == "postgresql":
            op.execute(f"DROP FUNCTION IF EXISTS trg_{table}_block_nonwhitelisted_update()")
            op.execute(f"DROP FUNCTION IF EXISTS trg_{table}_block_delete()")
