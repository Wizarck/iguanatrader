"""observability tables — api_cost_events + config_changes + audit_log

Slice O1 (``observability-cost-meter``) third migration. Plants the three
append-only tables for the observability bounded context (per data-model
§3.1, §3.5; design D8). All three are marked
``__tablename_is_append_only__ = True`` on their ORM mappings (slice-3 L1
listener); this migration adds the L2 BEFORE-trigger DDL so raw-SQL
mutations also fail (per slice-3 design D3).

Revision chaining (per cross-slice merge plan)
==============================================

The Wave-2 merge plan numbers the slice migrations as:

- R1 ``research-foundations`` → ``0003_research_tables``
- T1 ``trading-foundations`` → ``0004_trading_tables``
- K1 ``risk-foundations`` → ``0005_risk_tables``
- P1 ``approval-channels`` → ``0006_approval_tables``
- O1 ``observability-cost-meter`` → ``0007_observability_tables`` (this file)

This migration declares ``down_revision='0006_approval_tables'``. When
the slice O1 branch lands BEFORE its predecessors (the merge order is
not guaranteed), Alembic ``upgrade head`` will fail with
``Can't locate revision identified by '0006_approval_tables'`` until the
intermediate slices land. CI integration tests for migration chain
verification are gated accordingly — they ``pytest.skip`` when the
predecessor is absent (see ``apps/api/tests/integration/persistence/``
for the existing alembic-chain test pattern).

Until the chain is complete, local dev hosts the slice-O1 schema by
running the ORM ``Base.metadata.create_all(...)`` path (the integration
suite uses this; production deployments wait for the full chain).

Revision ID: 0007
Revises: 0006_approval_tables
Created at: 2026-05-06T00:00:00Z
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_observability_tables"
down_revision: str | None = "0006_approval_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Append-only L2 trigger DDL (per slice-3 design D3). SQLite ``BEFORE
# UPDATE`` / ``BEFORE DELETE`` triggers raising via ``RAISE(FAIL, ...)``
# refuse the mutation at driver level. Postgres v1.5 will emit
# ``RAISE EXCEPTION`` instead — gated by dialect detection at upgrade time.
def _create_append_only_triggers(table_name: str) -> None:
    """Plant BEFORE UPDATE / DELETE triggers refusing mutations on ``table_name``."""
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "sqlite":
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_no_update
            BEFORE UPDATE ON {table_name}
            BEGIN
                SELECT RAISE(FAIL, '{table_name} is append-only');
            END;
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_no_delete
            BEFORE DELETE ON {table_name}
            BEGIN
                SELECT RAISE(FAIL, '{table_name} is append-only');
            END;
            """
        )
    elif dialect == "postgresql":
        op.execute(
            f"""
            CREATE OR REPLACE FUNCTION raise_{table_name}_append_only()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION '{table_name} is append-only';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_no_update
            BEFORE UPDATE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION raise_{table_name}_append_only();
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_no_delete
            BEFORE DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION raise_{table_name}_append_only();
            """
        )


def _drop_append_only_triggers(table_name: str) -> None:
    """Drop the L2 triggers (reverse of :func:`_create_append_only_triggers`)."""
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS {table_name}_no_update")
        op.execute(f"DROP TRIGGER IF EXISTS {table_name}_no_delete")
    elif dialect == "postgresql":
        op.execute(f"DROP TRIGGER IF EXISTS {table_name}_no_update ON {table_name}")
        op.execute(f"DROP TRIGGER IF EXISTS {table_name}_no_delete ON {table_name}")
        op.execute(f"DROP FUNCTION IF EXISTS raise_{table_name}_append_only()")


def upgrade() -> None:
    # ----- api_cost_events ------------------------------------------------
    op.create_table(
        "api_cost_events",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("node", sa.Text(), nullable=True),
        sa.Column("tokens_input", sa.Integer(), nullable=False),
        sa.Column("tokens_output", sa.Integer(), nullable=False),
        sa.Column(
            "cost_usd",
            sa.Numeric(precision=12, scale=6),
            nullable=False,
        ),
        sa.Column(
            "cached",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("prompt_hash", sa.Text(), nullable=True),
        sa.Column(
            "metadata_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("routine_run_id", sa.CHAR(36), nullable=True),
        sa.Column("correlation_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_cost_events")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_api_cost_events_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "tokens_input >= 0",
            name=op.f("ck_api_cost_events_tokens_input_nonneg"),
        ),
        sa.CheckConstraint(
            "tokens_output >= 0",
            name=op.f("ck_api_cost_events_tokens_output_nonneg"),
        ),
        sa.CheckConstraint(
            "cost_usd >= 0",
            name=op.f("ck_api_cost_events_cost_usd_nonneg"),
        ),
    )
    op.create_index(
        op.f("ix_api_cost_events_tenant_id_created_at"),
        "api_cost_events",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_api_cost_events_routine_run_id"),
        "api_cost_events",
        ["routine_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_api_cost_events_provider_model_created_at"),
        "api_cost_events",
        ["provider", "model", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_api_cost_events_cached"),
        "api_cost_events",
        ["cached"],
        unique=False,
    )
    _create_append_only_triggers("api_cost_events")

    # ----- config_changes -------------------------------------------------
    op.create_table(
        "config_changes",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("actor_user_id", sa.CHAR(36), nullable=False),
        sa.Column("entity_kind", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column(
            "before_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "after_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_config_changes")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_config_changes_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_config_changes_actor_user_id_users"),
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        op.f("ix_config_changes_tenant_id_created_at"),
        "config_changes",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_config_changes_entity_kind_entity_id"),
        "config_changes",
        ["entity_kind", "entity_id"],
        unique=False,
    )
    _create_append_only_triggers("config_changes")

    # ----- audit_log ------------------------------------------------------
    op.create_table(
        "audit_log",
        sa.Column("id", sa.CHAR(36), nullable=False),
        # Nullable per design D8 — NULL = cross-tenant ops-global event.
        sa.Column("tenant_id", sa.CHAR(36), nullable=True),
        sa.Column("actor_kind", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=True),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column("entity_kind", sa.Text(), nullable=True),
        sa.Column("entity_id", sa.Text(), nullable=True),
        sa.Column(
            "metadata_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_audit_log_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "actor_kind IN ('user','system','scheduler','channel')",
            name=op.f("ck_audit_log_actor_kind_allowed"),
        ),
    )
    op.create_index(
        op.f("ix_audit_log_tenant_id_created_at"),
        "audit_log",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_log_entity_kind_entity_id"),
        "audit_log",
        ["entity_kind", "entity_id"],
        unique=False,
    )
    _create_append_only_triggers("audit_log")


def downgrade() -> None:
    _drop_append_only_triggers("audit_log")
    op.drop_index(op.f("ix_audit_log_entity_kind_entity_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_tenant_id_created_at"), table_name="audit_log")
    op.drop_table("audit_log")

    _drop_append_only_triggers("config_changes")
    op.drop_index(
        op.f("ix_config_changes_entity_kind_entity_id"),
        table_name="config_changes",
    )
    op.drop_index(
        op.f("ix_config_changes_tenant_id_created_at"),
        table_name="config_changes",
    )
    op.drop_table("config_changes")

    _drop_append_only_triggers("api_cost_events")
    op.drop_index(op.f("ix_api_cost_events_cached"), table_name="api_cost_events")
    op.drop_index(
        op.f("ix_api_cost_events_provider_model_created_at"),
        table_name="api_cost_events",
    )
    op.drop_index(
        op.f("ix_api_cost_events_routine_run_id"),
        table_name="api_cost_events",
    )
    op.drop_index(
        op.f("ix_api_cost_events_tenant_id_created_at"),
        table_name="api_cost_events",
    )
    op.drop_table("api_cost_events")
