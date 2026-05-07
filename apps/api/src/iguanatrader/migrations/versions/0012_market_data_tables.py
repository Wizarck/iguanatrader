"""market_data_bars + market_data_sync_audit (slice T4-followup-market-data §2.6).

Two tables:

* ``market_data_bars`` — historical OHLCV bars. Mutable + UPSERT on
  ``(tenant_id, symbol, timeframe, ts)``: IBKR may re-emit adjusted
  prices for splits/dividends, and re-ingestion is the canonical fix.
* ``market_data_sync_audit`` — append-only invocation log of every
  ingestion call (daemon-cron, cli-sync, cli-backfill). Used both for
  rate-limit (count of rows in trailing hour) and ops dashboards.

Migration slot ``0012`` reserved per
``.ai-playbook/specs/migration-slot-reservation.md``. Latest existing
slot is ``0011_orchestration_tables``.

Revision ID: 0012_market_data_tables
Revises: 0011_orchestration_tables
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_market_data_tables"
down_revision: str | None = "0011_orchestration_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_data_bars",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("timeframe", sa.Text(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(18, 8), nullable=False),
        sa.Column("high", sa.Numeric(18, 8), nullable=False),
        sa.Column("low", sa.Numeric(18, 8), nullable=False),
        sa.Column("close", sa.Numeric(18, 8), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_market_data_bars")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_market_data_bars_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "symbol",
            "timeframe",
            "ts",
            name="uq_market_data_bars_tenant_id_symbol_timeframe_ts",
        ),
    )
    op.create_index(
        "ix_market_data_bars_tenant_id",
        "market_data_bars",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_market_data_bars_lookup",
        "market_data_bars",
        ["tenant_id", "symbol", "timeframe", "ts"],
        unique=False,
    )

    op.create_table(
        "market_data_sync_audit",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column(
            "invoked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column("invoked_by", sa.Text(), nullable=False),
        sa.Column("symbols", sa.JSON(), nullable=False),
        sa.Column("timeframe", sa.Text(), nullable=False),
        sa.Column("lookback_bars", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "bars_written",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "duration_ms",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_market_data_sync_audit")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_market_data_sync_audit_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "invoked_by IN ('daemon-cron','cli-sync','cli-backfill')",
            name=op.f("ck_market_data_sync_audit_invoked_by_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('success','partial','failed','rate_limited')",
            name=op.f("ck_market_data_sync_audit_status_allowed"),
        ),
    )
    op.create_index(
        "ix_market_data_sync_audit_tenant_id_invoked_at",
        "market_data_sync_audit",
        ["tenant_id", "invoked_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_market_data_sync_audit_tenant_id_invoked_at",
        table_name="market_data_sync_audit",
    )
    op.drop_table("market_data_sync_audit")
    op.drop_index("ix_market_data_bars_lookup", table_name="market_data_bars")
    op.drop_index("ix_market_data_bars_tenant_id", table_name="market_data_bars")
    op.drop_table("market_data_bars")
