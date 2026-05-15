"""trailing_stop_audit — append-only audit table for trailing-stop ratchets.

Slice ``orchestration-trailing-stops-cron`` task 1. Activates the
:func:`compute_trailing_stop` pure function (shipped in PR #163) by
giving its cron-sweep caller a persistence target.

One row is inserted per evaluation where the function returned
``reason='trailed'`` (i.e. the candidate stop strictly exceeds the
previous stop — a real ratchet). ``no_update`` and
``trigger_not_reached`` outcomes are logged at DEBUG/INFO but NOT
persisted, to avoid O(open_trades * 4 sweeps/hr * 8 hr * 250 days)
audit-row bloat for a value (~daily new high) that arrives sparsely.

The table doubles as the **stop-history lookup**: the sweep service
resolves a trade's *current* stop as ``latest(trailing_stop_audit.new_stop
WHERE trade_id = ?)`` falling back to ``TradeProposal.stop_price`` when
no audit row exists yet. This keeps the ``Trade`` row write-once beyond
its existing whitelist (``state, closed_at, exit_reason, realised_pnl``)
— stop drift lives in this dedicated audit log rather than re-opening
the ``Trade`` whitelist.

**Tenant scoping**: row carries ``tenant_id`` so the
slice-3 ``tenant_listener`` filters cross-tenant reads automatically.

**Indexes**:
* ``(trade_id, swept_at DESC)`` — the canonical lookup is
  "latest audit row for this trade".
* ``(tenant_id)`` — supports the listener's per-tenant filter on bulk
  reads (operator dashboards).

**Append-only**: the ORM model in ``contexts/risk/orm.py`` declares
``__tablename_is_append_only__ = True`` + ``__append_only_mutable_columns__
= frozenset()``. The audit-row IS the historical record; you do not
mutate prior sweeps.

Revision ID: 0016_trailing_stop_audit
Revises: 0015_trade_exit_columns
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_trailing_stop_audit"
down_revision: str | None = "0015_trade_exit_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trailing_stop_audit",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("trade_id", sa.CHAR(36), nullable=False),
        sa.Column("swept_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("old_stop", sa.Numeric(18, 8), nullable=False),
        sa.Column("new_stop", sa.Numeric(18, 8), nullable=False),
        sa.Column("highest_close_since_entry", sa.Numeric(18, 8), nullable=False),
        sa.Column("atr", sa.Numeric(18, 8), nullable=False),
        sa.Column("bars_evaluated", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trailing_stop_audit")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_trailing_stop_audit_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["trade_id"],
            ["trades.id"],
            name=op.f("fk_trailing_stop_audit_trade_id_trades"),
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_trailing_stop_audit_trade_id_swept_at",
        "trailing_stop_audit",
        ["trade_id", sa.text("swept_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_trailing_stop_audit_tenant_id",
        "trailing_stop_audit",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_trailing_stop_audit_tenant_id", table_name="trailing_stop_audit")
    op.drop_index(
        "ix_trailing_stop_audit_trade_id_swept_at",
        table_name="trailing_stop_audit",
    )
    op.drop_table("trailing_stop_audit")
