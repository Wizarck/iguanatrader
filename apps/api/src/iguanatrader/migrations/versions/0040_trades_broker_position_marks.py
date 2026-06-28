"""trades: broker-reconciled position marks (avg_entry_price / unrealized_pnl)

Slice ``portfolio-broker-position-marks``. IBKR's ``reqExecutions`` does not
reliably surface fills older than the prior session, so a position can be live
broker-side (``list_positions`` returns it with an ``avgCost`` + ``unrealizedPnL``)
while the local ``fills`` table has zero rows for it — leaving the fill-derived
average entry + unrealized P&L forever null on the positions dashboard
("pendiente de ejecución"). This adds three nullable columns the on-boot /
on-demand reconcile UPDATEs from the broker's authoritative position book:

* ``avg_entry_price`` — IBKR ``avgCost``; the positions API uses it as the real
  entry when the fill-weighted average is null.
* ``unrealized_pnl`` — IBKR mark-to-market P&L as of ``marks_updated_at``.
* ``marks_updated_at`` — when the reconcile last restamped the two above.

All three join the ``trades`` L1 append-only whitelist
(``Trade.__append_only_mutable_columns__``) + the L2 mirror's
``MUTABLE_COLUMNS['trades']`` snapshot. ``NON_WHITELISTED_COLUMNS['trades']`` is
UNCHANGED — the L2 ``trg_trades_no_update`` predicate only fires on the
immutable column set, so these new mutable columns are implicitly permitted and
the trigger does NOT need recreating here.

Additive + nullable → instant on Postgres (metadata-only), no backfill.

Revision ID: 0040_trades_broker_position_marks
Revises: 0039_approval_exit_action_type
Created at: 2026-06-28T00:00:00Z
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040_trades_broker_position_marks"
down_revision: str | None = "0039_approval_exit_action_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "trades",
        sa.Column("avg_entry_price", sa.Numeric(18, 8), nullable=True),
    )
    op.add_column(
        "trades",
        sa.Column("unrealized_pnl", sa.Numeric(18, 8), nullable=True),
    )
    op.add_column(
        "trades",
        sa.Column("marks_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    # SQLite (dev/test) needs batch mode to drop columns; Postgres handles the
    # batched DDL transparently.
    with op.batch_alter_table("trades") as batch:
        batch.drop_column("marks_updated_at")
        batch.drop_column("unrealized_pnl")
        batch.drop_column("avg_entry_price")
