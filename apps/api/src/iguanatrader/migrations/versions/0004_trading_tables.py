"""trading-context tables — strategy_configs, trade_proposals, trades, orders, fills, equity_snapshots

Slice T1 ``trading-models-interfaces`` migration. Creates the 6 trading
bounded-context tables per ``docs/data-model.md §3.2`` plus the cross-
slice FK ``trade_proposals.research_brief_id → research_briefs(id)``
(declared NULLABLE because the research domain may not be operational
when the migration runs in lower environments — once R5 lands the
synthesizer, populated values become the norm).

**Merge order constraint (design D5)**: ``down_revision`` points at
``"0003_research_tables"`` (slice R1's migration). R1 MUST merge into
``main`` before this migration's PR is merged — otherwise
``alembic upgrade head`` on a fresh DB fails because the parent
revision is not present. CI gate: ``test_trading_migration.py`` runs
``alembic upgrade head`` on a fresh SQLite DB and asserts both
revisions are applied. Until R1 lands, the slice-T1 branch keeps this
``down_revision`` declaration unchanged; on rebase, no edit is needed
because R1's revision string is the canonical anchor.

Revision ID: 0004_trading_tables
Revises: 0003_research_tables
Created at: 2026-05-05T00:00:00Z
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_trading_tables"
# Per design D5: anchor at R1's revision. The slice-T1 PR cannot merge
# until R1 (``research-bitemporal-schema``) is merged into ``main``;
# ``test_trading_migration.py`` enforces the gate by attempting
# ``alembic upgrade head`` on a fresh DB.
down_revision: str | None = "0003_research_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strategy_configs",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("strategy_kind", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strategy_configs")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_strategy_configs_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "strategy_kind",
            "symbol",
            name=op.f("uq_strategy_configs_tenant_id_strategy_kind_symbol"),
        ),
    )
    op.create_index(
        op.f("ix_strategy_configs_tenant_id_enabled"),
        "strategy_configs",
        ["tenant_id", "enabled"],
        unique=False,
    )

    op.create_table(
        "trade_proposals",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("strategy_config_id", sa.CHAR(36), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 8), nullable=False),
        sa.Column("entry_price_indicative", sa.Numeric(18, 8), nullable=False),
        sa.Column("stop_price", sa.Numeric(18, 8), nullable=False),
        sa.Column("confidence_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("reasoning", sa.JSON(), nullable=False),
        # Cross-slice FK to R1's ``research_briefs`` table; nullable per
        # design D5 (proposals before research domain is operational
        # carry NULL; post-R5 the synthesizer always populates).
        sa.Column("research_brief_id", sa.CHAR(36), nullable=True),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("correlation_id", sa.CHAR(36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trade_proposals")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_trade_proposals_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_config_id"],
            ["strategy_configs.id"],
            name=op.f("fk_trade_proposals_strategy_config_id_strategy_configs"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["research_brief_id"],
            ["research_briefs.id"],
            name=op.f("fk_trade_proposals_research_brief_id_research_briefs"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "side IN ('buy','sell')",
            name=op.f("ck_trade_proposals_side_allowed"),
        ),
        sa.CheckConstraint(
            "mode IN ('paper','live')",
            name=op.f("ck_trade_proposals_mode_allowed"),
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name=op.f("ck_trade_proposals_quantity_positive"),
        ),
        sa.CheckConstraint(
            "confidence_score IS NULL OR (confidence_score BETWEEN 0 AND 1)",
            name=op.f("ck_trade_proposals_confidence_score_range"),
        ),
    )
    op.create_index(
        op.f("ix_trade_proposals_tenant_id_created_at"),
        "trade_proposals",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trade_proposals_strategy_config_id"),
        "trade_proposals",
        ["strategy_config_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trade_proposals_correlation_id"),
        "trade_proposals",
        ["correlation_id"],
        unique=False,
    )

    op.create_table(
        "trades",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("proposal_id", sa.CHAR(36), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 8), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trades")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_trades_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["trade_proposals.id"],
            name=op.f("fk_trades_proposal_id_trade_proposals"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "side IN ('buy','sell')",
            name=op.f("ck_trades_side_allowed"),
        ),
        sa.CheckConstraint(
            "mode IN ('paper','live')",
            name=op.f("ck_trades_mode_allowed"),
        ),
        sa.CheckConstraint(
            "state IN ('open','closed_filled','closed_force_exit','closed_canceled')",
            name=op.f("ck_trades_state_allowed"),
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name=op.f("ck_trades_quantity_positive"),
        ),
    )
    op.create_index(
        op.f("ix_trades_tenant_id_state"),
        "trades",
        ["tenant_id", "state"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trades_tenant_id_symbol_state"),
        "trades",
        ["tenant_id", "symbol", "state"],
        unique=False,
    )
    op.create_index(
        op.f("ix_trades_proposal_id"),
        "trades",
        ["proposal_id"],
        unique=False,
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("trade_id", sa.CHAR(36), nullable=False),
        sa.Column("broker", sa.Text(), nullable=False),
        sa.Column("broker_order_id", sa.Text(), nullable=True),
        sa.Column("order_type", sa.Text(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 8), nullable=False),
        sa.Column("limit_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("stop_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_orders_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["trade_id"],
            ["trades.id"],
            name=op.f("fk_orders_trade_id_trades"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "broker IN ('ibkr','simulated')",
            name=op.f("ck_orders_broker_allowed"),
        ),
        sa.CheckConstraint(
            "order_type IN ('market','limit','stop','stop_limit')",
            name=op.f("ck_orders_order_type_allowed"),
        ),
        sa.CheckConstraint(
            "side IN ('buy','sell')",
            name=op.f("ck_orders_side_allowed"),
        ),
        sa.CheckConstraint(
            "state IN ('new','submitted','partially_filled','filled','canceled','rejected')",
            name=op.f("ck_orders_state_allowed"),
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name=op.f("ck_orders_quantity_positive"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "broker",
            "broker_order_id",
            name=op.f("uq_orders_tenant_id"),
        ),
    )
    op.create_index(
        op.f("ix_orders_tenant_id_state"),
        "orders",
        ["tenant_id", "state"],
        unique=False,
    )
    op.create_index(
        op.f("ix_orders_trade_id"),
        "orders",
        ["trade_id"],
        unique=False,
    )

    op.create_table(
        "fills",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("order_id", sa.CHAR(36), nullable=False),
        sa.Column("quantity_filled", sa.Numeric(18, 8), nullable=False),
        sa.Column("fill_price", sa.Numeric(18, 8), nullable=False),
        sa.Column(
            "commission",
            sa.Numeric(18, 8),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "commission_currency",
            sa.CHAR(3),
            nullable=False,
            server_default=sa.text("'USD'"),
        ),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("broker_fill_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fills")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_fills_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_fills_order_id_orders"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "quantity_filled > 0",
            name=op.f("ck_fills_quantity_filled_positive"),
        ),
    )
    op.create_index(
        op.f("ix_fills_tenant_id_filled_at"),
        "fills",
        ["tenant_id", "filled_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_fills_order_id"),
        "fills",
        ["order_id"],
        unique=False,
    )

    op.create_table(
        "equity_snapshots",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("account_equity", sa.Numeric(18, 8), nullable=False),
        sa.Column("cash_balance", sa.Numeric(18, 8), nullable=False),
        sa.Column(
            "realized_pnl_today",
            sa.Numeric(18, 8),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "unrealized_pnl",
            sa.Numeric(18, 8),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "currency",
            sa.CHAR(3),
            nullable=False,
            server_default=sa.text("'USD'"),
        ),
        sa.Column("snapshot_kind", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_equity_snapshots")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_equity_snapshots_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "mode IN ('paper','live')",
            name=op.f("ck_equity_snapshots_mode_allowed"),
        ),
        # Per data-model §7.2 update — drop ``'tick'`` (and ``'hourly'``);
        # authoritative enum is ``('event','minute','daily')``. The §3.2
        # row in the doc still lists the legacy enum but §7.2 supersedes
        # (per design Open Question Q3 + tasks.md 2.4 inline note).
        sa.CheckConstraint(
            "snapshot_kind IN ('event','minute','daily')",
            name=op.f("ck_equity_snapshots_snapshot_kind_allowed"),
        ),
    )
    op.create_index(
        op.f("ix_equity_snapshots_tenant_id_mode_created_at"),
        "equity_snapshots",
        ["tenant_id", "mode", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    # Reverse-FK order: equity_snapshots → fills → orders → trades →
    # trade_proposals → strategy_configs.
    op.drop_index(
        op.f("ix_equity_snapshots_tenant_id_mode_created_at"),
        table_name="equity_snapshots",
    )
    op.drop_table("equity_snapshots")

    op.drop_index(op.f("ix_fills_order_id"), table_name="fills")
    op.drop_index(op.f("ix_fills_tenant_id_filled_at"), table_name="fills")
    op.drop_table("fills")

    op.drop_index(op.f("ix_orders_trade_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_tenant_id_state"), table_name="orders")
    op.drop_table("orders")

    op.drop_index(op.f("ix_trades_proposal_id"), table_name="trades")
    op.drop_index(
        op.f("ix_trades_tenant_id_symbol_state"),
        table_name="trades",
    )
    op.drop_index(op.f("ix_trades_tenant_id_state"), table_name="trades")
    op.drop_table("trades")

    op.drop_index(
        op.f("ix_trade_proposals_correlation_id"),
        table_name="trade_proposals",
    )
    op.drop_index(
        op.f("ix_trade_proposals_strategy_config_id"),
        table_name="trade_proposals",
    )
    op.drop_index(
        op.f("ix_trade_proposals_tenant_id_created_at"),
        table_name="trade_proposals",
    )
    op.drop_table("trade_proposals")

    op.drop_index(
        op.f("ix_strategy_configs_tenant_id_enabled"),
        table_name="strategy_configs",
    )
    op.drop_table("strategy_configs")
