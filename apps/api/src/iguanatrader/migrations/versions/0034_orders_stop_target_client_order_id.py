"""orders — persist protective stop/target + deterministic client_order_id

Audit findings #6 (minimal) + #7:

* **#6 (minimal)** — the entry order discarded the strategy's protective
  ``stop_price``/``target_price``. ``orders.stop_price`` already existed but
  was never populated on the entry leg; ``target_price`` was missing entirely.
  This adds ``orders.target_price`` so the protective intent is recorded on
  the order row (the service now copies both from the proposal). Native
  IBKR bracket/OCO transmission is the deferred #6-bracket follow-up.

* **#7** — a timed-out submission may still be live at the broker, yet the
  DB marked it terminally ``rejected``. This adds:
  - ``orders.client_order_id`` (deterministic per logical order) + a
    per-tenant UNIQUE constraint so a retry/reconcile dedupes instead of
    doubling the position;
  - a new non-terminal ``timeout_pending`` value in the order-state CHECK.

SQLite cannot ``ALTER`` a CHECK / add a constraint in place — Alembic's
``batch_alter_table`` (``render_as_batch=True`` in env.py) rewrites the
table, copying rows through. The bare constraint name re-resolves via the
project naming convention to ``ck_orders_state_allowed`` (mirrors 0032).

Revision ID: 0034_orders_stop_target_client_order_id
Revises: 0033_trading_append_only_l2_triggers
Created at: 2026-06-01T00:00:00Z
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034_orders_stop_target_client_order_id"
down_revision: str | None = "0033_trading_append_only_l2_triggers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATE_NEW = (
    "state IN ('new','submitted','partially_filled','filled',"
    "'canceled','rejected','timeout_pending')"
)
_STATE_OLD = "state IN ('new','submitted','partially_filled','filled','canceled','rejected')"


def upgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.add_column(sa.Column("target_price", sa.Numeric(18, 8), nullable=True))
        batch_op.add_column(sa.Column("client_order_id", sa.Uuid(), nullable=True))
        batch_op.drop_constraint("state_allowed", type_="check")
        batch_op.create_check_constraint("state_allowed", _STATE_NEW)
        batch_op.create_unique_constraint(
            "uq_orders_tenant_client_order_id",
            ["tenant_id", "client_order_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_constraint("uq_orders_tenant_client_order_id", type_="unique")
        batch_op.drop_constraint("state_allowed", type_="check")
        batch_op.create_check_constraint("state_allowed", _STATE_OLD)
        batch_op.drop_column("client_order_id")
        batch_op.drop_column("target_price")
