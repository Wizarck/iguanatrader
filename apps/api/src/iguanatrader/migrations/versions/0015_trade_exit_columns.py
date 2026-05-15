"""trades — add exit_reason + realised_pnl columns

Slice ``trades-add-exit-and-realised-pnl-columns`` task 1. Adds two
nullable columns to ``trades`` so the follow-up
``wire-risk-state-real-data`` slice can populate v1.5
:class:`RiskState` fields from concrete data:

* ``exit_reason`` TEXT NULL — categorical reason the trade closed.
  Allowed values: ``'stop'``, ``'target'``, ``'manual'``, ``'expiry'``
  (CHECK constraint ``ck_trades_exit_reason_allowed`` enforces the
  enum at the DB layer). NULL means "unknown" — legacy rows (pre-
  2026-05-15) and any future row that has not yet been closed.
  ``stoploss_guard`` counts only rows whose ``exit_reason == 'stop'``,
  so NULL contributes zero to the consecutive-stoploss tally.
* ``realised_pnl`` NUMERIC(18, 8) NULL — closed-trade P&L in the
  account currency. Populated at close-flow time alongside
  ``exit_reason`` (the close-flow wiring lands in the separate slice
  ``trades-close-flow-exit-classification``). ``daily_loss`` /
  ``weekly_loss`` caps aggregate this column over
  ``WHERE closed_at >= <window_start>``; NULL rows are skipped
  (``SUM`` ignores NULL).

**Backfill**: NONE — by design. The risk protections in v1.5 treat
NULL as "no contribution"; populating historical rows would require
re-running the close-flow analysis against fills, which is out of
scope for this prerequisite slice (see proposal §Out of scope).

**Whitelist update**: the ORM model extends
``__append_only_mutable_columns__`` to include the two new columns
(see ``contexts/trading/models.py::Trade``). Without that change the
append-only listener would reject the UPDATE when the (future)
close-flow service populates them. The whitelist edit is part of
this migration's PR but does not require DDL.

SQLite supports ``ALTER TABLE ADD COLUMN`` directly; we still use
``batch_alter_table`` to match the project's slice-3 convention
(``render_as_batch=True`` in env.py) and to keep CHECK-constraint DDL
SQLite-compatible (SQLite cannot add a table-level CHECK via plain
``ALTER TABLE``; batch mode rewrites the table).

Revision ID: 0015_trade_exit_columns
Revises: 0014_user_recovery_channels
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_trade_exit_columns"
down_revision: str | None = "0014_user_recovery_channels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("trades") as batch_op:
        batch_op.add_column(
            sa.Column(
                "exit_reason",
                sa.Text(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "realised_pnl",
                sa.Numeric(18, 8),
                nullable=True,
            )
        )
        batch_op.create_check_constraint(
            "ck_trades_exit_reason_allowed",
            "exit_reason IS NULL OR exit_reason IN " "('stop', 'target', 'manual', 'expiry')",
        )


def downgrade() -> None:
    with op.batch_alter_table("trades") as batch_op:
        batch_op.drop_constraint(
            "ck_trades_exit_reason_allowed",
            type_="check",
        )
        batch_op.drop_column("realised_pnl")
        batch_op.drop_column("exit_reason")
