"""tenant_trading_modes — per-tenant per-mode trading enable flag

Slice ``dual-daemon-mode-toggle-and-reconcile`` first migration. Backs the
``/api/v1/daemons/{mode}/toggle`` endpoint and the persistent mode chip in
the web header. Each row is a per-(tenant, mode) flag with audit columns
(who toggled, when, why).

Seeded for every existing tenant on upgrade: ``(paper, enabled=1)`` +
``(live, enabled=0)``. Paper-by-default preserves the current
single-daemon behaviour; live requires an explicit operator action via
the UI.

FK ``tenant_id → tenants.id`` uses ``ondelete=CASCADE`` (not the project's
usual RESTRICT) because these rows are pure config, not historical
truth — deleting a tenant should sweep their mode flags with no orphan
risk. FK ``last_toggled_by_user_id → users.id`` uses ``ondelete=SET NULL``
so the audit row survives user deletion (the operator may have been
deactivated but the toggle still happened).

Revision ID: 0026_tenant_trading_modes
Revises: 0025_trade_proposal_target_price
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_tenant_trading_modes"
down_revision: str | None = "0025_trade_proposal_target_price"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_trading_modes",
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "last_toggled_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column("last_toggled_by_user_id", sa.CHAR(36), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "mode",
            name=op.f("pk_tenant_trading_modes"),
        ),
        sa.CheckConstraint(
            "mode IN ('paper','live')",
            name=op.f("ck_tenant_trading_modes_mode_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_tenant_trading_modes_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["last_toggled_by_user_id"],
            ["users.id"],
            name=op.f("fk_tenant_trading_modes_last_toggled_by_user_id_users"),
            ondelete="SET NULL",
        ),
    )

    op.execute(
        sa.text(
            "INSERT INTO tenant_trading_modes "
            "(tenant_id, mode, enabled, last_toggled_at) "
            "SELECT id, 'paper', true, CURRENT_TIMESTAMP FROM tenants"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO tenant_trading_modes "
            "(tenant_id, mode, enabled, last_toggled_at) "
            "SELECT id, 'live', false, CURRENT_TIMESTAMP FROM tenants"
        )
    )


def downgrade() -> None:
    op.drop_table("tenant_trading_modes")
