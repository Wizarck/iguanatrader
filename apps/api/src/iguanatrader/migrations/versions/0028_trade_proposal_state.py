"""trade_proposals — add ``state`` + ``rejection_reason`` + ``rejected_at``

Slice ``dual-daemon-mode-toggle-and-reconcile`` follow-up migration. The
slice's drain semantic needs a per-proposal lifecycle column on the
``trade_proposals`` row itself so ``daemon_drained`` can be distinguished
from other rejection reasons without crossing into the
``approval_decisions`` audit log every time the count is queried.

Columns added:

* ``state`` TEXT NOT NULL DEFAULT ``'pending_approval'`` — lifecycle
  enum ``{'pending_approval', 'approved', 'rejected', 'expired'}``.
  Mirrors ``approval_decisions.outcome`` semantics (granted → approved,
  rejected → rejected, timeout → expired) plus an explicit
  ``pending_approval`` for rows still awaiting a decision and a
  ``rejected`` value reused for daemon-drained proposals.
* ``rejection_reason`` TEXT NULL — free-form reason; canonical sentinel
  values include ``'daemon_drained'`` (drain), ``'user_declined'``
  (default for human rejection), ``'approval_timeout'`` (sweeper), plus
  whatever the rejection event carries.
* ``rejected_at`` TIMESTAMPTZ NULL — wall-clock at the moment the row
  transitioned to ``rejected`` OR ``expired``.

**Backfill**: existing rows are SET to ``state='approved'`` to keep them
out of any future toggle-off drain sweep. Conservatively safe — legacy
proposals were either acted upon (have downstream trades/orders) or
sit in tombstone limbo where re-rejecting them adds no value. The new
``pending_approval`` semantic applies forward to newly-INSERTed rows.

**Append-only impact**: ``TradeProposal.__append_only_mutable_columns__``
gains the 3 new columns so the slice-3 append-only listener permits the
UPDATEs that the drain logic + the approval-handler state propagation
issue. Same column-whitelist pattern that ``Trade`` (and the trades-add-
exit-and-realised-pnl-columns slice) already uses.

Revision ID: 0028_trade_proposal_state
Revises: 0027_daemon_heartbeats
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_trade_proposal_state"
down_revision: str | None = "0027_daemon_heartbeats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("trade_proposals") as batch_op:
        batch_op.add_column(
            sa.Column(
                "state",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'pending_approval'"),
            )
        )
        batch_op.add_column(
            sa.Column("rejection_reason", sa.Text(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "rejected_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.create_check_constraint(
            "ck_trade_proposals_state_allowed",
            "state IN ('pending_approval','approved','rejected','expired')",
        )

    op.execute(sa.text("UPDATE trade_proposals SET state = 'approved'"))


def downgrade() -> None:
    with op.batch_alter_table("trade_proposals") as batch_op:
        batch_op.drop_constraint("ck_trade_proposals_state_allowed", type_="check")
        batch_op.drop_column("rejected_at")
        batch_op.drop_column("rejection_reason")
        batch_op.drop_column("state")
