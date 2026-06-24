"""risk tables — risk_evaluations, risk_overrides, kill_switch_state, kill_switch_events

Slice K1 (``risk-engine-protections``) ships the four risk-domain
tables per ``docs/data-model.md §3.3``. Append-only constraints are
enforced by the slice-3 ORM ``before_flush`` listener (L1) + by the
``__tablename_is_append_only__`` flag on each ORM model. CHECK
constraints in this migration are the L2 last-line guarantee.

T1 BRIDGE NOTE: At K1 propose-time, slice T1 (``trading-models-
interfaces``) is unmerged so ``trade_proposals.id`` does not yet
exist. K1's ``proposal_id`` columns are therefore created without an
emitted FK constraint to ``trade_proposals``; a follow-up migration
``0004b_risk_fk.py`` adds the FK once T1's tables exist. The columns
are still indexed via ``ix_*_proposal_id``, and tenant scoping +
RESTRICT cascades on the existing FKs (``tenants.id``, ``users.id``,
``risk_evaluations.id``) protect the audit chain.

The ``kill_switch_state.last_event_id`` self-referential FK to
``kill_switch_events.id`` is also deferred — SQLite's ``ALTER TABLE``
limitations make it cleaner to add via a follow-up if needed; for K1
the column is plain ``Uuid`` (the cache can still hold the latest
event id without a hard FK because the event log is append-only).

Per design D7 open question + tasks 2.6: this migration adds ``'cli'``
to the ``kill_switch_events.source`` CHECK list (data-model §3.3
canonically omits it; K1 spec deviation documented inline).

Revision ID: 0004
Revises: 0002
Created at: 2026-05-05T00:00:00Z
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_risk_tables"
down_revision: str | None = "0004_trading_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. risk_evaluations — append-only.
    op.create_table(
        "risk_evaluations",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("proposal_id", sa.CHAR(36), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("cap_type_breached", sa.Text(), nullable=True),
        sa.Column("current_pct", sa.Numeric(8, 6), nullable=True),
        sa.Column(
            "state_snapshot",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("clip_quantity", sa.Numeric(18, 8), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_evaluations")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_risk_evaluations_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "outcome IN ('allow','reject','clip')",
            name=op.f("ck_risk_evaluations_outcome_allowed"),
        ),
        sa.CheckConstraint(
            "cap_type_breached IS NULL OR cap_type_breached IN "
            "('per_trade','daily_loss','weekly_loss','max_open','max_drawdown')",
            name=op.f("ck_risk_evaluations_cap_type_breached_allowed"),
        ),
    )
    op.create_index(
        op.f("ix_risk_evaluations_proposal_id"),
        "risk_evaluations",
        ["proposal_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_risk_evaluations_tenant_id_outcome_created_at"),
        "risk_evaluations",
        ["tenant_id", "outcome", "created_at"],
        unique=False,
    )

    # 2. risk_overrides — append-only audit, ≥20 char reason CHECK.
    op.create_table(
        "risk_overrides",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("proposal_id", sa.CHAR(36), nullable=False),
        sa.Column("risk_evaluation_id", sa.CHAR(36), nullable=False),
        sa.Column("authorised_by_user_id", sa.CHAR(36), nullable=False),
        sa.Column("reason_text", sa.Text(), nullable=False),
        sa.Column("confirmation_chain", sa.JSON(), nullable=False),
        sa.Column("state_snapshot_at_override", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_overrides")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_risk_overrides_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["risk_evaluation_id"],
            ["risk_evaluations.id"],
            name=op.f("fk_risk_overrides_risk_evaluation_id_risk_evaluations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["authorised_by_user_id"],
            ["users.id"],
            name=op.f("fk_risk_overrides_authorised_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "length(reason_text) >= 20",
            name=op.f("ck_risk_overrides_reason_text_min_length"),
        ),
    )
    op.create_index(
        op.f("ix_risk_overrides_proposal_id"),
        "risk_overrides",
        ["proposal_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_risk_overrides_tenant_id_created_at"),
        "risk_overrides",
        ["tenant_id", "created_at"],
        unique=False,
    )

    # 3. kill_switch_events — append-only authoritative log.
    op.create_table(
        "kill_switch_events",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("transition", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("actor_user_id", sa.CHAR(36), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kill_switch_events")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_kill_switch_events_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_kill_switch_events_actor_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "transition IN ('activated','deactivated')",
            name=op.f("ck_kill_switch_events_transition_allowed"),
        ),
        # K1 spec deviation: 'cli' added to the canonical
        # data-model §3.3 source list per design D7 open question.
        sa.CheckConstraint(
            "source IN ('file_flag','env_var','channel_command',"
            "'dashboard_button','automatic_backoff','automatic_cap_breach','cli')",
            name=op.f("ck_kill_switch_events_source_allowed"),
        ),
    )
    op.create_index(
        op.f("ix_kill_switch_events_tenant_id_created_at"),
        "kill_switch_events",
        ["tenant_id", "created_at"],
        unique=False,
    )

    # 4. kill_switch_state — mutable single row per tenant (NFR-R5 cache).
    op.create_table(
        "kill_switch_state",
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("last_event_id", sa.CHAR(36), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_kill_switch_state")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_kill_switch_state_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        # last_event_id self-ref FK to kill_switch_events.id deferred —
        # see migration docstring rationale.
    )


def downgrade() -> None:
    op.drop_table("kill_switch_state")
    op.drop_index(
        op.f("ix_kill_switch_events_tenant_id_created_at"),
        table_name="kill_switch_events",
    )
    op.drop_table("kill_switch_events")
    op.drop_index(
        op.f("ix_risk_overrides_tenant_id_created_at"),
        table_name="risk_overrides",
    )
    op.drop_index(
        op.f("ix_risk_overrides_proposal_id"),
        table_name="risk_overrides",
    )
    op.drop_table("risk_overrides")
    op.drop_index(
        op.f("ix_risk_evaluations_tenant_id_outcome_created_at"),
        table_name="risk_evaluations",
    )
    op.drop_index(
        op.f("ix_risk_evaluations_proposal_id"),
        table_name="risk_evaluations",
    )
    op.drop_table("risk_evaluations")
