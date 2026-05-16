"""trades — add journal_narrative + journal_generated_at + journal_model

Slice ``llm-observability-and-signals``. Adds three nullable columns to
``trades`` so the LLM-generated post-mortem journal (endpoint
``POST /api/v1/trades/{id}/journal``) can persist its output:

* ``journal_narrative`` TEXT NULL — LLM-generated 2-4 paragraph
  narrative of the trade outcome (what worked / what didn't / lessons).
  NULL means "no journal written yet". The journal endpoint
  short-circuits with HTTP 409 when this column is non-NULL unless the
  caller passes ``?regenerate=true``.
* ``journal_generated_at`` TIMESTAMP NULL — when the narrative was
  produced. Independent of ``closed_at`` because a trade can be
  journalled days after it closes.
* ``journal_model`` VARCHAR(64) NULL — Anthropic model id that
  produced the narrative (e.g. ``claude-3-5-haiku-20241022``). Helps
  debug when journal quality regresses after a model swap.

**Append-only whitelist**: the three columns extend the
``Trade.__append_only_mutable_columns__`` frozenset so the slice-3
append-only listener permits the UPDATE that the journal endpoint
issues. Without that change every journal write would raise
``AppendOnlyViolationError``.

**No backfill**: journal is opt-in per trade; columns stay NULL on
historical rows until an operator explicitly POSTs the endpoint for
each one.

SQLite supports ``ALTER TABLE ADD COLUMN`` directly; we use
``batch_alter_table`` to match the project's slice-3 convention.

Revision ID: 0018_trade_journal_narrative
Revises: 0017_trade_state_simplify
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_trade_journal_narrative"
down_revision: str | None = "0017_trade_state_simplify"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("trades") as batch_op:
        batch_op.add_column(
            sa.Column(
                "journal_narrative",
                sa.Text(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "journal_generated_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "journal_model",
                sa.String(64),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("trades") as batch_op:
        batch_op.drop_column("journal_model")
        batch_op.drop_column("journal_generated_at")
        batch_op.drop_column("journal_narrative")
