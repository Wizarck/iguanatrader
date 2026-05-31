"""widen risk_evaluations.current_pct + allow v1.5 cap types

Two schema-drift fixes against ``risk_evaluations`` (audit findings #36 + #41):

* **#36** — the ``cap_type_breached`` CHECK omitted ``stoploss_guard`` and
  ``cooldown_period``, yet both are real v1.5 protections wired into the
  engine pipeline (``contexts/risk/engine.py``). The moment either cap is
  configured and breaches, the engine emits a Decision with that cap_type
  and the INSERT into ``risk_evaluations`` violates the CHECK — crashing
  the evaluation. This widens the allow-list to include them.

* **#41** — ``current_pct`` was ``Numeric(8, 6)`` (max 99.999999). A
  utilisation percentage can legitimately exceed 100 (e.g. a drawdown
  breach reported as >100%), overflowing the precision on Postgres and
  failing the INSERT. Widened to ``Numeric(12, 6)``.

SQLite cannot ``ALTER`` a CHECK or column type in place — Alembic's
``batch_alter_table`` (``render_as_batch=True`` in env.py) rewrites the
table, copying rows through. Drops pass the BARE constraint name so the
naming convention re-resolves it to
``ck_risk_evaluations_cap_type_breached_allowed`` (mirrors 0002).

Revision ID: 0032_risk_eval_cap_types_and_pct_width
Revises: 0031_trade_proposal_risk_review
Created at: 2026-05-31T00:00:00Z
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032_risk_eval_cap_types_and_pct_width"
down_revision: str | None = "0031_trade_proposal_risk_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CAP_TYPES_NEW = (
    "cap_type_breached IS NULL OR cap_type_breached IN "
    "('per_trade','daily_loss','weekly_loss','max_open','max_drawdown',"
    "'stoploss_guard','cooldown_period')"
)
_CAP_TYPES_OLD = (
    "cap_type_breached IS NULL OR cap_type_breached IN "
    "('per_trade','daily_loss','weekly_loss','max_open','max_drawdown')"
)


def upgrade() -> None:
    with op.batch_alter_table("risk_evaluations") as batch_op:
        batch_op.alter_column(
            "current_pct",
            existing_type=sa.Numeric(8, 6),
            type_=sa.Numeric(12, 6),
            existing_nullable=True,
        )
        batch_op.drop_constraint("cap_type_breached_allowed", type_="check")
        batch_op.create_check_constraint("cap_type_breached_allowed", _CAP_TYPES_NEW)


def downgrade() -> None:
    with op.batch_alter_table("risk_evaluations") as batch_op:
        batch_op.drop_constraint("cap_type_breached_allowed", type_="check")
        batch_op.create_check_constraint("cap_type_breached_allowed", _CAP_TYPES_OLD)
        batch_op.alter_column(
            "current_pct",
            existing_type=sa.Numeric(12, 6),
            type_=sa.Numeric(8, 6),
            existing_nullable=True,
        )
