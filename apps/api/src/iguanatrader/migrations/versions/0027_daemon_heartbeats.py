"""daemon_heartbeats — per-(tenant, mode) liveness row updated by each daemon

Slice ``dual-daemon-mode-toggle-and-reconcile`` second migration. Replaces the
in-process ``DaemonHealthRegistry`` design with a DB-backed table so the
``api`` container can read daemon liveness without an HTTP round-trip to the
daemon container (api + daemon processes do not share memory; design §D6).

Each daemon upserts one row every ~10s with the current IBKR connection
state. ``GET /api/v1/status`` reads it and reports ``ib_connected=false`` if
``last_heartbeat_at`` is older than 30s (stale-detection).

No seed — rows are created on the first heartbeat write per (tenant, mode).

Revision ID: 0027_daemon_heartbeats
Revises: 0026_tenant_trading_modes
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_daemon_heartbeats"
down_revision: str | None = "0026_tenant_trading_modes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daemon_heartbeats",
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column(
            "last_heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "ib_connected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "mode",
            name=op.f("pk_daemon_heartbeats"),
        ),
        sa.CheckConstraint(
            "mode IN ('paper','live')",
            name=op.f("ck_daemon_heartbeats_mode_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_daemon_heartbeats_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("daemon_heartbeats")
