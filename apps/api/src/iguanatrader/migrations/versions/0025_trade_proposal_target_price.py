"""trade_proposals — add ``target_price`` for take-profit auto-close.

Slice ``exit-classification-stop-hit-sweep``. The brief synthesizer
already emits a 12-month target price (see the three-pillar prompt's
``**Target price**`` line + the coherence validator added in #247),
but the value was discarded by the proposal builder — only
``stop_price`` made it onto the proposal row. Result: an auto-close
sweep had no way to recognise a take-profit hit. The auto-close
loop (``CloseTradeRequested(reason="target")``) needs a value on the
proposal to compare bar prices against.

Schema change:

* ``trade_proposals.target_price`` NUMERIC(18, 8) NULL — LLM-emitted
  target (USD). NULL on legacy rows + on proposals where the prompt
  did not emit a target (low-confidence HOLD paths). The stop-hit
  sweep skips target evaluation when NULL.

**Coherence rule** (enforced upstream by the synthesiser's
``_check_recommendation_coherence`` and the three-pillar prompt): for
a long, ``target_price >= entry_price_indicative``; for a short,
``target_price <= entry_price_indicative``. This migration does NOT
add a CHECK constraint because the validator paths can downgrade an
incoherent proposal to HOLD with a NULL target — the column needs to
accept that state.

**No backfill**: existing proposals stay NULL. The follow-up slice
that ships the stop-hit sweep simply treats NULL as "no target", which
matches the pre-slice behaviour.

Revision ID: 0025_trade_proposal_target_price
Revises: 0024_ingest_runs_table
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_trade_proposal_target_price"
down_revision: str | None = "0024_ingest_runs_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("trade_proposals") as batch_op:
        batch_op.add_column(
            sa.Column(
                "target_price",
                sa.Numeric(18, 8),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("trade_proposals") as batch_op:
        batch_op.drop_column("target_price")
