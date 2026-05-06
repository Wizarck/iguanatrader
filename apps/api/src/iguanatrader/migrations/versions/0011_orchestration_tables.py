"""orchestration tables — routine_runs + alert_events (slice O2).

Per slice O2 design D6:

* ``routine_runs`` — every cron execution. Append-only-on-success
  semantics (status moves through pending → running → terminal-only-once);
  documented in slice-3 listener as a narrow exception to append-only
  via ``__append_only_mutable_columns__``.
* ``alert_events`` — every classified event from
  :func:`alert_filter.classify_event`. Pure append-only.

Migration slot deviation: tasks.md called for ``0007``. Slot is taken
(R5 0009, R3 0010, etc); this migration ships as ``0011`` with
``down_revision='0010_research_sources_tier_b_c'``. Documented in
retro per the running migration-slot-collision pattern (now 6 slices
in a row).

Revision ID: 0011_orchestration_tables
Revises: 0010_research_sources_tier_b_c
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_orchestration_tables"
down_revision: str | None = "0010_research_sources_tier_b_c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "routine_runs",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("routine_name", sa.Text(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(18, 8), nullable=True),
        sa.Column("digest_payload", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_routine_runs")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_routine_runs_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "routine_name",
            "scheduled_at",
            "tenant_id",
            name="uq_routine_runs_routine_name_scheduled_at_tenant_id",
        ),
        sa.CheckConstraint(
            "routine_name IN ('premarket','midday','postmarket','weekly_review')",
            name=op.f("ck_routine_runs_routine_name_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('pending','running','success','timeout','error',"
            "'skipped_budget','skipped_duplicate')",
            name=op.f("ck_routine_runs_status_allowed"),
        ),
    )
    op.create_index(
        "ix_routine_runs_tenant_id_scheduled_at",
        "routine_runs",
        ["tenant_id", "scheduled_at"],
        unique=False,
    )

    op.create_table(
        "alert_events",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("event_name", sa.Text(), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("routing_decision", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("correlation_id", sa.CHAR(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alert_events")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_alert_events_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "tier IN (1,2,3)",
            name=op.f("ck_alert_events_tier_allowed"),
        ),
    )
    op.create_index(
        "ix_alert_events_tenant_id_tier_created_at",
        "alert_events",
        ["tenant_id", "tier", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_alert_events_event_name_created_at",
        "alert_events",
        ["event_name", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_alert_events_event_name_created_at", table_name="alert_events")
    op.drop_index("ix_alert_events_tenant_id_tier_created_at", table_name="alert_events")
    op.drop_table("alert_events")
    op.drop_index("ix_routine_runs_tenant_id_scheduled_at", table_name="routine_runs")
    op.drop_table("routine_runs")
