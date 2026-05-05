"""research domain — 7 tables + L2 append-only triggers (slice R1)

Per design D1-D5 (``openspec/changes/research-bitemporal-schema/design.md``):

* 7 tables in FK-safe creation order: ``research_sources`` →
  ``symbol_universe`` → ``watchlist_configs`` → ``research_facts`` →
  ``research_briefs`` → ``corporate_events`` → ``analyst_ratings``.
* All temporal + provenance + hybrid-payload CHECK constraints from
  data-model §3.7 (verbatim).
* Per-table BEFORE UPDATE / BEFORE DELETE triggers (L2 enforcement) on
  each append-only table. The ``research_facts`` UPDATE trigger has the
  narrow exception per design D1: permit ``recorded_to: NULL → :ts`` when
  every other column is unchanged; raise otherwise.
* Dialect-aware trigger DDL (``op.get_bind().dialect.name``): SQLite uses
  ``RAISE(FAIL, ...)``; Postgres uses a ``CREATE FUNCTION ... LANGUAGE
  plpgsql`` + ``CREATE TRIGGER`` pair. Postgres branch lands in v1.5; this
  migration emits both branches but is exercised only on SQLite at R1.

**Migration number deviation**: tasks.md called for ``0002_research_tables``
with ``down_revision='0001'``. Slice 4 (``auth-jwt-cookie``) shipped
``0002_users_role_enum.py`` post tasks.md authoring, taking that slot. R1
ships as ``0003`` with ``down_revision='0002'``. No semantic change — the
schema still lands strictly after both slice-3 ``0001`` and slice-4
``0002`` migrations.

Revision ID: 0003
Revises: 0002
Created at: 2026-05-06T00:00:00Z
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from iguanatrader.migrations._research_trigger_helpers import (
    FULLY_APPEND_ONLY_TABLES as _FULLY_APPEND_ONLY_TABLES,
)
from iguanatrader.migrations._research_trigger_helpers import SQLITE_TRIGGER_SQL

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# Append-only L2 trigger DDL — dialect-aware
# ---------------------------------------------------------------------------
# SQLite trigger DDL is centralised in
# ``iguanatrader.migrations._research_trigger_helpers.SQLITE_TRIGGER_SQL``
# so tests can import the same DDL the migration emits (tests use
# Base.metadata.create_all rather than running the full Alembic chain).
# ---------------------------------------------------------------------------


def _emit_postgres_full_lock_triggers(table: str) -> None:
    """Postgres equivalent — RAISE EXCEPTION via plpgsql."""
    fn_name = f"trg_{table}_block_mutation"
    op.execute(f"""
        CREATE OR REPLACE FUNCTION {fn_name}() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'append-only: % on {table} forbidden', TG_OP;
            RETURN NULL;
        END;
        $$;
        """)
    op.execute(f"""
        CREATE TRIGGER trg_{table}_no_update
        BEFORE UPDATE ON {table}
        FOR EACH ROW EXECUTE FUNCTION {fn_name}();
        """)
    op.execute(f"""
        CREATE TRIGGER trg_{table}_no_delete
        BEFORE DELETE ON {table}
        FOR EACH ROW EXECUTE FUNCTION {fn_name}();
        """)


def _emit_postgres_research_facts_triggers() -> None:
    """Postgres counterpart — narrow recorded_to exception via plpgsql."""
    op.execute("""
        CREATE OR REPLACE FUNCTION trg_research_facts_guard_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.recorded_to IS NULL
               AND NEW.recorded_to IS NOT NULL
               AND OLD.id IS NOT DISTINCT FROM NEW.id
               AND OLD.tenant_id IS NOT DISTINCT FROM NEW.tenant_id
               AND OLD.source_id IS NOT DISTINCT FROM NEW.source_id
               AND OLD.symbol_universe_id IS NOT DISTINCT FROM NEW.symbol_universe_id
               AND OLD.fact_kind IS NOT DISTINCT FROM NEW.fact_kind
               AND OLD.value_numeric IS NOT DISTINCT FROM NEW.value_numeric
               AND OLD.value_text IS NOT DISTINCT FROM NEW.value_text
               AND OLD.value_jsonb IS NOT DISTINCT FROM NEW.value_jsonb
               AND OLD.unit IS NOT DISTINCT FROM NEW.unit
               AND OLD.currency IS NOT DISTINCT FROM NEW.currency
               AND OLD.effective_from IS NOT DISTINCT FROM NEW.effective_from
               AND OLD.effective_to IS NOT DISTINCT FROM NEW.effective_to
               AND OLD.recorded_from IS NOT DISTINCT FROM NEW.recorded_from
               AND OLD.source_url IS NOT DISTINCT FROM NEW.source_url
               AND OLD.retrieval_method IS NOT DISTINCT FROM NEW.retrieval_method
               AND OLD.retrieved_at IS NOT DISTINCT FROM NEW.retrieved_at
               AND OLD.raw_payload_inline IS NOT DISTINCT FROM NEW.raw_payload_inline
               AND OLD.raw_payload_path IS NOT DISTINCT FROM NEW.raw_payload_path
               AND OLD.raw_payload_sha256 IS NOT DISTINCT FROM NEW.raw_payload_sha256
               AND OLD.raw_payload_size_bytes IS NOT DISTINCT FROM NEW.raw_payload_size_bytes
               AND OLD.confidence IS NOT DISTINCT FROM NEW.confidence
               AND OLD.metadata IS NOT DISTINCT FROM NEW.metadata
               AND OLD.created_at IS NOT DISTINCT FROM NEW.created_at
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'append-only: only recorded_to NULL->ts supersession permitted on research_facts';
        END;
        $$;
        """)
    op.execute("""
        CREATE TRIGGER trg_research_facts_no_update
        BEFORE UPDATE ON research_facts
        FOR EACH ROW EXECUTE FUNCTION trg_research_facts_guard_update();
        """)
    op.execute("""
        CREATE OR REPLACE FUNCTION trg_research_facts_block_delete() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'append-only: DELETE on research_facts forbidden';
        END;
        $$;
        """)
    op.execute("""
        CREATE TRIGGER trg_research_facts_no_delete
        BEFORE DELETE ON research_facts
        FOR EACH ROW EXECUTE FUNCTION trg_research_facts_block_delete();
        """)


# ---------------------------------------------------------------------------
# Schema upgrade / downgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 1. research_sources — cross-tenant catalogue (no tenant_id).
    op.create_table(
        "research_sources",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("pit_class", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_sources")),
        sa.CheckConstraint(
            "tier IN (1,2,3,4)",
            name=op.f("ck_research_sources_tier_allowed"),
        ),
        sa.CheckConstraint(
            "pit_class IN ('A','B','C')",
            name=op.f("ck_research_sources_pit_class_allowed"),
        ),
    )

    # 2. symbol_universe — per-tenant, mutable.
    op.create_table(
        "symbol_universe",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("exchange", sa.Text(), nullable=False),
        sa.Column("sector", sa.Text(), nullable=True),
        sa.Column("industry", sa.Text(), nullable=True),
        sa.Column("market_cap_bucket", sa.Text(), nullable=True),
        sa.Column("ipo_date", sa.Date(), nullable=True),
        sa.Column("delisted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_symbol_universe")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_symbol_universe_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "symbol",
            "exchange",
            name="uq_symbol_universe_tenant_id_symbol_exchange",
        ),
        sa.CheckConstraint(
            "market_cap_bucket IS NULL OR market_cap_bucket IN "
            "('mega','large','mid','small','micro')",
            name=op.f("ck_symbol_universe_market_cap_bucket_allowed"),
        ),
    )
    op.create_index(
        "ix_symbol_universe_tenant_id_sector",
        "symbol_universe",
        ["tenant_id", "sector"],
        unique=False,
    )

    # 3. watchlist_configs — per-tenant, mutable.
    op.create_table(
        "watchlist_configs",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("symbol_universe_id", sa.CHAR(36), nullable=False),
        sa.Column("tier", sa.Text(), nullable=False),
        sa.Column("methodology", sa.Text(), nullable=False),
        sa.Column("methodology_params", sa.JSON(), nullable=True),
        sa.Column("brief_refresh_schedule", sa.Text(), nullable=False),
        sa.Column("brief_refresh_cron", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_watchlist_configs")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_watchlist_configs_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["symbol_universe_id"],
            ["symbol_universe.id"],
            name=op.f("fk_watchlist_configs_symbol_universe_id_symbol_universe"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "symbol_universe_id",
            name="uq_watchlist_configs_tenant_id_symbol_universe_id",
        ),
        sa.CheckConstraint(
            "tier IN ('primary','secondary')",
            name=op.f("ck_watchlist_configs_tier_allowed"),
        ),
        sa.CheckConstraint(
            "methodology IN ('three_pillar','canslim','magic_formula'," "'qarp','multi_factor')",
            name=op.f("ck_watchlist_configs_methodology_allowed"),
        ),
        sa.CheckConstraint(
            "brief_refresh_schedule IN ('daily','weekly','manual')",
            name=op.f("ck_watchlist_configs_brief_refresh_schedule_allowed"),
        ),
    )
    op.create_index(
        "ix_watchlist_configs_tenant_id_tier",
        "watchlist_configs",
        ["tenant_id", "tier"],
        unique=False,
    )

    # 4. research_facts — bitemporal append-only with hybrid payload.
    op.create_table(
        "research_facts",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("symbol_universe_id", sa.CHAR(36), nullable=True),
        sa.Column("fact_kind", sa.Text(), nullable=False),
        sa.Column("value_numeric", sa.Numeric(28, 12), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_jsonb", sa.JSON(), nullable=True),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("currency", sa.CHAR(3), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("retrieval_method", sa.Text(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_payload_inline", sa.JSON(), nullable=True),
        sa.Column("raw_payload_path", sa.Text(), nullable=True),
        sa.Column("raw_payload_sha256", sa.CHAR(64), nullable=True),
        sa.Column("raw_payload_size_bytes", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_facts")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_research_facts_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["research_sources.id"],
            name=op.f("fk_research_facts_source_id_research_sources"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["symbol_universe_id"],
            ["symbol_universe.id"],
            name=op.f("fk_research_facts_symbol_universe_id_symbol_universe"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "length(source_url) > 0",
            name=op.f("ck_research_facts_source_url_not_empty"),
        ),
        sa.CheckConstraint(
            "retrieval_method IN ('api','scrape','manual','llm')",
            name=op.f("ck_research_facts_retrieval_method_allowed"),
        ),
        sa.CheckConstraint(
            "effective_from <= COALESCE(effective_to, '9999-12-31')",
            name=op.f("ck_research_facts_effective_temporal_sanity"),
        ),
        sa.CheckConstraint(
            "recorded_from <= COALESCE(recorded_to, '9999-12-31')",
            name=op.f("ck_research_facts_recorded_temporal_sanity"),
        ),
        sa.CheckConstraint(
            "value_numeric IS NOT NULL OR value_text IS NOT NULL " "OR value_jsonb IS NOT NULL",
            name=op.f("ck_research_facts_at_least_one_value"),
        ),
        sa.CheckConstraint(
            "(raw_payload_inline IS NULL) <> (raw_payload_path IS NULL)",
            name=op.f("ck_research_facts_payload_xor_inline_path"),
        ),
        sa.CheckConstraint(
            "raw_payload_path IS NULL OR raw_payload_sha256 IS NOT NULL",
            name=op.f("ck_research_facts_payload_path_requires_sha256"),
        ),
        sa.CheckConstraint(
            "raw_payload_size_bytes IS NULL OR raw_payload_size_bytes < 16384 "
            "OR raw_payload_path IS NOT NULL",
            name=op.f("ck_research_facts_payload_size_tier_consistency"),
        ),
        sa.CheckConstraint(
            "raw_payload_size_bytes IS NULL OR raw_payload_size_bytes >= 0",
            name=op.f("ck_research_facts_payload_size_nonneg"),
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=op.f("ck_research_facts_confidence_unit_interval"),
        ),
    )
    op.create_index(
        "ix_research_facts_tenant_id_symbol_universe_id_fact_kind",
        "research_facts",
        ["tenant_id", "symbol_universe_id", "fact_kind"],
        unique=False,
    )
    op.create_index(
        "ix_research_facts_tenant_id_fact_kind_effective_from",
        "research_facts",
        ["tenant_id", "fact_kind", "effective_from"],
        unique=False,
    )
    op.create_index(
        "ix_research_facts_tenant_id_recorded_from",
        "research_facts",
        ["tenant_id", "recorded_from"],
        unique=False,
    )
    op.create_index(
        "ix_research_facts_source_id",
        "research_facts",
        ["source_id"],
        unique=False,
    )

    # 5. research_briefs — append-only versioned.
    op.create_table(
        "research_briefs",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("symbol_universe_id", sa.CHAR(36), nullable=False),
        sa.Column("watchlist_config_id", sa.CHAR(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("methodology", sa.Text(), nullable=False),
        sa.Column("thesis_text", sa.Text(), nullable=False),
        sa.Column("score_overall", sa.Numeric(5, 4), nullable=True),
        sa.Column("score_components", sa.JSON(), nullable=True),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("audit_trail", sa.JSON(), nullable=False),
        sa.Column("llm_provider", sa.Text(), nullable=False),
        sa.Column("llm_model", sa.Text(), nullable=False),
        sa.Column("llm_input_tokens", sa.Integer(), nullable=False),
        sa.Column("llm_output_tokens", sa.Integer(), nullable=False),
        sa.Column(
            "llm_cache_hit_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "partial",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_briefs")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_research_briefs_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["symbol_universe_id"],
            ["symbol_universe.id"],
            name=op.f("fk_research_briefs_symbol_universe_id_symbol_universe"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["watchlist_config_id"],
            ["watchlist_configs.id"],
            name=op.f("fk_research_briefs_watchlist_config_id_watchlist_configs"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "symbol_universe_id",
            "version",
            name="uq_research_briefs_tenant_id_symbol_universe_id_version",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name=op.f("ck_research_briefs_version_positive"),
        ),
        sa.CheckConstraint(
            "methodology IN ('three_pillar','canslim','magic_formula'," "'qarp','multi_factor')",
            name=op.f("ck_research_briefs_methodology_allowed"),
        ),
        sa.CheckConstraint(
            "score_overall IS NULL OR (score_overall >= 0 AND score_overall <= 1)",
            name=op.f("ck_research_briefs_score_unit_interval"),
        ),
        sa.CheckConstraint(
            "llm_input_tokens >= 0",
            name=op.f("ck_research_briefs_input_tokens_nonneg"),
        ),
        sa.CheckConstraint(
            "llm_output_tokens >= 0",
            name=op.f("ck_research_briefs_output_tokens_nonneg"),
        ),
        sa.CheckConstraint(
            "llm_cache_hit_tokens >= 0",
            name=op.f("ck_research_briefs_cache_hit_tokens_nonneg"),
        ),
    )
    op.create_index(
        "ix_research_briefs_tenant_id_symbol_universe_id_created_at",
        "research_briefs",
        ["tenant_id", "symbol_universe_id", "created_at"],
        unique=False,
    )

    # 6. corporate_events — append-only.
    op.create_table(
        "corporate_events",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("symbol_universe_id", sa.CHAR(36), nullable=False),
        sa.Column("event_kind", sa.Text(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_corporate_events")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_corporate_events_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["symbol_universe_id"],
            ["symbol_universe.id"],
            name=op.f("fk_corporate_events_symbol_universe_id_symbol_universe"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["research_sources.id"],
            name=op.f("fk_corporate_events_source_id_research_sources"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "event_kind IN ('earnings_release','ex_dividend','split',"
            "'merger_announcement','fda_approval','spinoff','tender_offer',"
            "'recall','other')",
            name=op.f("ck_corporate_events_event_kind_allowed"),
        ),
        sa.CheckConstraint(
            "length(source_url) > 0",
            name=op.f("ck_corporate_events_source_url_not_empty"),
        ),
    )
    op.create_index(
        "ix_corporate_events_tenant_id_symbol_universe_id_event_date",
        "corporate_events",
        ["tenant_id", "symbol_universe_id", "event_date"],
        unique=False,
    )
    op.create_index(
        "ix_corporate_events_tenant_id_event_kind_event_date",
        "corporate_events",
        ["tenant_id", "event_kind", "event_date"],
        unique=False,
    )

    # 7. analyst_ratings — append-only.
    op.create_table(
        "analyst_ratings",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("symbol_universe_id", sa.CHAR(36), nullable=False),
        sa.Column("firm_name", sa.Text(), nullable=False),
        sa.Column("analyst_name", sa.Text(), nullable=True),
        sa.Column("rating", sa.Text(), nullable=False),
        sa.Column("previous_rating", sa.Text(), nullable=True),
        sa.Column("price_target", sa.Numeric(18, 8), nullable=True),
        sa.Column(
            "price_target_currency",
            sa.CHAR(3),
            nullable=True,
            server_default=sa.text("'USD'"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analyst_ratings")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_analyst_ratings_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["symbol_universe_id"],
            ["symbol_universe.id"],
            name=op.f("fk_analyst_ratings_symbol_universe_id_symbol_universe"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["research_sources.id"],
            name=op.f("fk_analyst_ratings_source_id_research_sources"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "rating IN ('strong_buy','buy','hold','sell'," "'strong_sell','withdrawn')",
            name=op.f("ck_analyst_ratings_rating_allowed"),
        ),
        sa.CheckConstraint(
            "length(source_url) > 0",
            name=op.f("ck_analyst_ratings_source_url_not_empty"),
        ),
    )
    op.create_index(
        "ix_analyst_ratings_tenant_id_symbol_universe_id_published_at",
        "analyst_ratings",
        ["tenant_id", "symbol_universe_id", "published_at"],
        unique=False,
    )
    op.create_index(
        "ix_analyst_ratings_tenant_id_firm_name_published_at",
        "analyst_ratings",
        ["tenant_id", "firm_name", "published_at"],
        unique=False,
    )

    # ---------------------------------------------------------------------
    # L2 append-only triggers — dialect-aware.
    # ---------------------------------------------------------------------

    if dialect == "sqlite":
        for sql in SQLITE_TRIGGER_SQL:
            op.execute(sql)
    elif dialect == "postgresql":
        for table in _FULLY_APPEND_ONLY_TABLES:
            _emit_postgres_full_lock_triggers(table)
        _emit_postgres_research_facts_triggers()
    else:
        # Other dialects (MySQL, etc.) are out of scope for v1.x — the L1
        # listener still enforces append-only at the ORM layer.
        pass


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Drop triggers + functions first (FK-safe — drop in reverse order).
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_research_facts_no_delete")
        op.execute("DROP TRIGGER IF EXISTS trg_research_facts_no_update")
        for table in _FULLY_APPEND_ONLY_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_update")
    elif dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_research_facts_no_delete ON research_facts")
        op.execute("DROP TRIGGER IF EXISTS trg_research_facts_no_update ON research_facts")
        op.execute("DROP FUNCTION IF EXISTS trg_research_facts_block_delete()")
        op.execute("DROP FUNCTION IF EXISTS trg_research_facts_guard_update()")
        for table in _FULLY_APPEND_ONLY_TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete ON {table}")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_update ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS trg_{table}_block_mutation()")

    # Drop tables in reverse FK order.
    op.drop_index(
        "ix_analyst_ratings_tenant_id_firm_name_published_at",
        table_name="analyst_ratings",
    )
    op.drop_index(
        "ix_analyst_ratings_tenant_id_symbol_universe_id_published_at",
        table_name="analyst_ratings",
    )
    op.drop_table("analyst_ratings")

    op.drop_index(
        "ix_corporate_events_tenant_id_event_kind_event_date",
        table_name="corporate_events",
    )
    op.drop_index(
        "ix_corporate_events_tenant_id_symbol_universe_id_event_date",
        table_name="corporate_events",
    )
    op.drop_table("corporate_events")

    op.drop_index(
        "ix_research_briefs_tenant_id_symbol_universe_id_created_at",
        table_name="research_briefs",
    )
    op.drop_table("research_briefs")

    op.drop_index("ix_research_facts_source_id", table_name="research_facts")
    op.drop_index(
        "ix_research_facts_tenant_id_recorded_from",
        table_name="research_facts",
    )
    op.drop_index(
        "ix_research_facts_tenant_id_fact_kind_effective_from",
        table_name="research_facts",
    )
    op.drop_index(
        "ix_research_facts_tenant_id_symbol_universe_id_fact_kind",
        table_name="research_facts",
    )
    op.drop_table("research_facts")

    op.drop_index(
        "ix_watchlist_configs_tenant_id_tier",
        table_name="watchlist_configs",
    )
    op.drop_table("watchlist_configs")

    op.drop_index(
        "ix_symbol_universe_tenant_id_sector",
        table_name="symbol_universe",
    )
    op.drop_table("symbol_universe")

    op.drop_table("research_sources")
