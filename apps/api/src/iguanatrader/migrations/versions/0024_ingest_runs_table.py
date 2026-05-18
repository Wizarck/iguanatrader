"""Create the ``ingest_runs`` tracking table (slice I7).

Per ingestion-wave roadmap §I7: each scheduled (or manual) source
ingestion writes one row to this table. Status / facts_inserted /
error_detail let the admin surface in
``GET /api/v1/admin/ingest-runs`` show which sources are healthy
and which silently dropped data on the last cron tick.

Tenant-scoped per the slice-3 listener convention.

Revision ID: 0024_ingest_runs_table
Revises: 0023_seed_research_source_edgartools_narrative
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_ingest_runs_table"
down_revision: str | None = "0023_seed_research_source_edgartools_narrative"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingest_runs",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.CHAR(36),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.Text(),
            sa.ForeignKey("research_sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "symbol_universe_id",
            sa.CHAR(36),
            sa.ForeignKey("symbol_universe.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("symbol", sa.Text(), nullable=True),
        sa.Column("invoked_by", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("facts_inserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('started','ok','error','cancelled')",
            name="ingest_runs_status_allowed",
        ),
    )
    op.create_index(
        "ix_ingest_runs_tenant_id_started_at",
        "ingest_runs",
        ["tenant_id", "started_at"],
    )
    op.create_index(
        "ix_ingest_runs_source_id_started_at",
        "ingest_runs",
        ["source_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ingest_runs_source_id_started_at", table_name="ingest_runs")
    op.drop_index("ix_ingest_runs_tenant_id_started_at", table_name="ingest_runs")
    op.drop_table("ingest_runs")
