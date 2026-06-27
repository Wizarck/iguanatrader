"""approval_requests — add action_type + trade_id; relax proposal_id NOT NULL

Slice ``urgent-exit-approval-plumbing`` (WS-5 PR-B). The HITL approval
machinery is keyed on ``proposal_id`` and its granted-decision bridge means
"OPEN a position" (``ApprovalProposalApproved`` → ``trading.ProposalApproved``
→ ``execute_on_approval_handler`` → ``place_order``). To reuse the exact same
fan-out / record-decision / timeout / Telegram machinery for an EXIT (sell-to-
close) without a granted exit ever firing a buy, the request row carries an
``action_type`` discriminator + the ``trade_id`` it acts on:

* ``action_type`` TEXT NOT NULL DEFAULT ``'entry'`` — ``'entry'`` (the existing
  open-a-position flow) or ``'exit'`` (close an open trade). The server default
  backfills every existing row to ``'entry'`` so behaviour is unchanged.
* ``trade_id`` UUID NULL — the open trade an exit-approval acts on; NULL for
  entry rows. App-enforced (no DB FK) to keep this a fast metadata-only
  ``ADD COLUMN`` on the live daemon — the urgent-exit advisor is the only
  writer and validates the trade exists before raising the approval.
* ``proposal_id`` relaxed to NULLable — an exit-approval has no proposal, so
  the column is NULL for exit rows (it stays NOT-NULL-in-practice for entries,
  set by the entry flow). The FK to ``trade_proposals(id)`` still constrains
  non-null values.

Reuses ``exit_reason='manual'`` for the actual close (a human-approved exit IS
a manual close), so the ``trades`` ``ck_trades_exit_reason_allowed`` CHECK is
untouched — no second migration.

``batch_alter_table`` (render_as_batch convention) keeps the nullability change
SQLite-compatible (SQLite cannot ``ALTER COLUMN DROP NOT NULL`` in place).

Revision ID: 0039_approval_exit_action_type
Revises: 0038_fix_proposals_trigger_json_cast
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039_approval_exit_action_type"
down_revision: str | None = "0038_fix_proposals_trigger_json_cast"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("approval_requests") as batch_op:
        batch_op.add_column(
            sa.Column(
                "action_type",
                sa.Text(),
                nullable=False,
                server_default="entry",
            )
        )
        batch_op.add_column(
            sa.Column(
                "trade_id",
                sa.Uuid(),
                nullable=True,
            )
        )
        batch_op.alter_column(
            "proposal_id",
            existing_type=sa.Uuid(),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("approval_requests") as batch_op:
        batch_op.alter_column(
            "proposal_id",
            existing_type=sa.Uuid(),
            nullable=False,
        )
        batch_op.drop_column("trade_id")
        batch_op.drop_column("action_type")
