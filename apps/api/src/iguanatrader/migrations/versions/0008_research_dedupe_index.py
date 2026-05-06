"""research_facts.dedupe_key column + partial unique index (slice R2).

Per slice R2 (``research-edgar-fred-adapters``) design D7:

* Adds nullable ``dedupe_key TEXT`` column to ``research_facts``.
* Creates a *partial* unique index on ``(tenant_id, dedupe_key)`` where
  ``dedupe_key IS NOT NULL`` — old R1 rows (no dedupe_key) are excluded
  from the uniqueness predicate.
* The Tier-A adapters (EDGAR/FRED/BLS/BEA) compute a deterministic
  ``dedupe_key`` per draft and the wrapper helper in
  :mod:`iguanatrader.contexts.research.sources._dedupe` short-circuits
  re-ingestion via a ``SELECT 1 ... WHERE dedupe_key = :key LIMIT 1``
  pre-check. The DB-level partial unique index is the canonical
  idempotency boundary (defence in depth: two concurrent ingest jobs
  cannot both insert).

**Migration slot deviation**: tasks.md called for slot ``0004``. Slots
``0004``-``0007`` were taken by the parallel Wave-3 slices (T2 trading,
T3 risk, T4 approval, O2 observability) that landed before R2. R2 ships
as ``0008`` with ``down_revision='0007_observability_tables'``. No
semantic change — the partial index lands strictly after the table
itself (``0003_research_tables``) and after every other Wave-3 schema.

Revision ID: 0008
Revises: 0007_observability_tables
Created at: 2026-05-06T00:00:00Z
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_research_dedupe_index"
down_revision: str | None = "0007_observability_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Index name kept short enough for the SQLite + Postgres 63-char NAMEDATALEN
# limit. Both dialects support partial indexes via the ``WHERE`` clause.
_INDEX_NAME = "idx_research_facts_dedupe_key"


def upgrade() -> None:
    op.add_column(
        "research_facts",
        sa.Column("dedupe_key", sa.Text(), nullable=True),
    )
    op.create_index(
        _INDEX_NAME,
        "research_facts",
        ["tenant_id", "dedupe_key"],
        unique=True,
        sqlite_where=sa.text("dedupe_key IS NOT NULL"),
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="research_facts")
    op.drop_column("research_facts", "dedupe_key")
