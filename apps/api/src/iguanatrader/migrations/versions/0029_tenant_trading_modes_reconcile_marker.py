"""tenant_trading_modes — add ``pending_reconcile_at`` marker column.

Slice ``dual-daemon-mode-toggle-and-reconcile`` Phase 3.5 follow-up.
The API and the daemon processes do not share an in-process bus
(Phase 4 compose split makes this explicit — they live in separate
containers), so the `POST /api/v1/daemons/{mode}/reconcile` endpoint
must persist the request somewhere the daemon will poll. This column
is that durable signal:

* API writes ``pending_reconcile_at = now()`` on every reconcile
  request.
* Daemon-side ``poll_for_state_changes`` (called from the 10s
  heartbeat cron) compares this column against an in-memory watermark
  and runs reconcile when newer. The watermark is reset to the column
  value after each successful reconcile.

NULL means "no reconcile has ever been requested for this row" — the
daemon's first heartbeat tick reads NULL, sets the watermark to NULL,
and only fires reconcile when the column transitions to a non-NULL
timestamp. Restarting the daemon re-reads NULL → idempotent on
re-request bounce.

Revision ID: 0029_tenant_trading_modes_reconcile_marker
Revises: 0028_trade_proposal_state
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029_tenant_trading_modes_reconcile_marker"
down_revision: str | None = "0028_trade_proposal_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tenant_trading_modes") as batch_op:
        batch_op.add_column(
            sa.Column(
                "pending_reconcile_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("tenant_trading_modes") as batch_op:
        batch_op.drop_column("pending_reconcile_at")
