"""research_audit_trail table for slice R5 (research-brief-synthesis).

Per slice R5 design D5: every computed metric in a research brief
persists its formula + inputs + intermediate steps + final output to a
dedicated append-only ``research_audit_trail`` table. This is the
"show your work" surface (FR70) — JTBD-4 anti-hallucination.

Schema:

* ``id`` — UUID primary key.
* ``tenant_id`` — slice-3 listener auto-injects on insert.
* ``brief_id`` — FK to ``research_briefs(id)`` ON DELETE RESTRICT.
* ``brief_version`` — denormalised for query performance.
* ``metric`` — short identifier (``forward_pe``, ``eps_growth_yoy``, …).
* ``formula`` — human-readable formula (``price / forward_eps``).
* ``inputs`` — JSONB ``[{name, value, fact_id?}, ...]``.
* ``steps`` — JSONB ``[{description, intermediate}, ...]`` — empty for
  one-shot lookups.
* ``final_output`` — TEXT (some metrics are labels, not numerics).
* ``methodology`` — denormalised; one of the 5 frameworks.
* ``llm_call_id`` — FK to ``api_cost_events(id)`` (O1) so an audit row
  is one click from the per-call cost ledger.
* ``created_at`` — server default.

Append-only: BEFORE UPDATE / BEFORE DELETE triggers per slice-3 D3
pattern. Indexes: ``(tenant_id, brief_id)``, ``(tenant_id, metric)``,
``(llm_call_id)``.

**Migration slot deviation**: tasks.md called for slot ``0008``. R2 took
slot ``0008`` (research_dedupe_index, archived 2026-05-06) before R5
applied. R5 ships as ``0009`` with ``down_revision='0008_research_dedupe_index'``.
Documented in PR body + retro per the R2 retro lesson on cross-slice
slot collisions.

Revision ID: 0009_research_audit_trail
Revises: 0008_research_dedupe_index
Created at: 2026-05-06T00:00:00Z
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_research_audit_trail"
down_revision: str | None = "0008_research_dedupe_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE = "research_audit_trail"
_TRG_NO_UPDATE = "trg_research_audit_trail_no_update"
_TRG_NO_DELETE = "trg_research_audit_trail_no_delete"
_FN_BLOCK = "trg_research_audit_trail_block_mutation"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("brief_id", sa.CHAR(36), nullable=False),
        sa.Column("brief_version", sa.Integer(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("formula", sa.Text(), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("final_output", sa.Text(), nullable=False),
        sa.Column("methodology", sa.Text(), nullable=False),
        sa.Column("llm_call_id", sa.CHAR(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_audit_trail")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_research_audit_trail_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["brief_id"],
            ["research_briefs.id"],
            name=op.f("fk_research_audit_trail_brief_id_research_briefs"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "methodology IN ('three_pillar','canslim','magic_formula','qarp','multi_factor')",
            name=op.f("ck_research_audit_trail_methodology_allowed"),
        ),
        sa.CheckConstraint(
            "brief_version >= 1",
            name=op.f("ck_research_audit_trail_brief_version_positive"),
        ),
    )
    op.create_index(
        "ix_research_audit_trail_tenant_id_brief_id",
        _TABLE,
        ["tenant_id", "brief_id"],
        unique=False,
    )
    op.create_index(
        "ix_research_audit_trail_tenant_id_metric",
        _TABLE,
        ["tenant_id", "metric"],
        unique=False,
    )
    op.create_index(
        "ix_research_audit_trail_llm_call_id",
        _TABLE,
        ["llm_call_id"],
        unique=False,
    )

    # Append-only L2 triggers — same pattern as slice-3 D3 + R1's
    # research_facts triggers from migration 0003.
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "sqlite":
        op.execute(f"""
            CREATE TRIGGER {_TRG_NO_UPDATE}
            BEFORE UPDATE ON {_TABLE}
            BEGIN
                SELECT RAISE(FAIL, 'append-only: UPDATE on research_audit_trail forbidden');
            END;
            """)
        op.execute(f"""
            CREATE TRIGGER {_TRG_NO_DELETE}
            BEFORE DELETE ON {_TABLE}
            BEGIN
                SELECT RAISE(FAIL, 'append-only: DELETE on research_audit_trail forbidden');
            END;
            """)
    elif dialect == "postgresql":
        op.execute(f"""
            CREATE OR REPLACE FUNCTION {_FN_BLOCK}() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'append-only: % on research_audit_trail forbidden', TG_OP;
                RETURN NULL;
            END;
            $$;
            """)
        op.execute(f"""
            CREATE TRIGGER {_TRG_NO_UPDATE}
            BEFORE UPDATE ON {_TABLE}
            FOR EACH ROW EXECUTE FUNCTION {_FN_BLOCK}();
            """)
        op.execute(f"""
            CREATE TRIGGER {_TRG_NO_DELETE}
            BEFORE DELETE ON {_TABLE}
            FOR EACH ROW EXECUTE FUNCTION {_FN_BLOCK}();
            """)


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS {_TRG_NO_DELETE}")
        op.execute(f"DROP TRIGGER IF EXISTS {_TRG_NO_UPDATE}")
    elif dialect == "postgresql":
        op.execute(f"DROP TRIGGER IF EXISTS {_TRG_NO_DELETE} ON {_TABLE}")
        op.execute(f"DROP TRIGGER IF EXISTS {_TRG_NO_UPDATE} ON {_TABLE}")
        op.execute(f"DROP FUNCTION IF EXISTS {_FN_BLOCK}()")

    op.drop_index("ix_research_audit_trail_llm_call_id", table_name=_TABLE)
    op.drop_index("ix_research_audit_trail_tenant_id_metric", table_name=_TABLE)
    op.drop_index("ix_research_audit_trail_tenant_id_brief_id", table_name=_TABLE)
    op.drop_table(_TABLE)
