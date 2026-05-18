"""trade_proposals — add A2 risk-review columns

Slice ``a2-risk-review-persist`` follow-up migration. The
:class:`AutoRiskReviewOnCreateHandler` (slice A2) already runs in
production but its persister is a no-op stub because the target columns
did not yet exist on ``trade_proposals``. This migration lands them so
the assessment can persist alongside the proposal row and be re-read by
the A1 dispatcher when it composes the Hermes payload.

Columns added (all NULL on existing rows — the assessor only ever
populates rows it produced):

* ``risk_score`` INTEGER NULL — bounded ``[0, 100]`` per
  :class:`ProposalRiskAssessment` contract; higher means riskier.
* ``risk_flags`` JSON NULL — list of categorical concern tags emitted
  by the assessor (e.g. ``["earnings_within_5d", "low_liquidity"]``).
* ``risk_rationale`` TEXT NULL — free-form 2-3 paragraph narrative the
  LLM produced explaining the score.
* ``risk_generated_at`` TIMESTAMPTZ NULL — wall-clock when the LLM
  call landed.
* ``risk_model`` VARCHAR(64) NULL — model identifier (e.g.
  ``claude-sonnet-4-6``) so audit + cost reconciliation can attribute
  the call.

CHECK constraint ``ck_trade_proposals_risk_score_range`` enforces the
score bound at DB level so a buggy assessor cannot persist garbage.

**Append-only impact**: ``TradeProposal.__append_only_mutable_columns__``
gains the 5 new columns so the slice-3 append-only listener permits the
single ``UPDATE trade_proposals SET risk_* = ...`` issued by the
:class:`AutoRiskReviewOnCreateHandler` persister adapter. Same column-
whitelist pattern that ``Trade`` (journal_*) and ``TradeProposal``
itself (state/rejection_reason/rejected_at) already use.

Revision ID: 0031_trade_proposal_risk_review
Revises: 0030_trades_exit_reason_ibkr_reconcile

Note: ``down_revision`` is finalised AFTER PR #266 (dual-daemon-followups)
merges to main — that PR ships migration ``0030_trades_exit_reason_ibkr_reconcile``.
Until then the A2 branch's alembic chain is informational only (the
test suite seeds via ``Base.metadata.create_all`` so the chain is not
exercised in pytest).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031_trade_proposal_risk_review"
down_revision: str | None = "0030_trades_exit_reason_ibkr_reconcile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("trade_proposals") as batch_op:
        batch_op.add_column(sa.Column("risk_score", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("risk_flags", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("risk_rationale", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "risk_generated_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("risk_model", sa.String(length=64), nullable=True))
        batch_op.create_check_constraint(
            "ck_trade_proposals_risk_score_range",
            "risk_score IS NULL OR (risk_score BETWEEN 0 AND 100)",
        )


def downgrade() -> None:
    with op.batch_alter_table("trade_proposals") as batch_op:
        batch_op.drop_constraint("ck_trade_proposals_risk_score_range", type_="check")
        batch_op.drop_column("risk_model")
        batch_op.drop_column("risk_generated_at")
        batch_op.drop_column("risk_rationale")
        batch_op.drop_column("risk_flags")
        batch_op.drop_column("risk_score")
