"""Seed ``research_sources`` row for the edgartools narrative adapter.

Slice ``I6`` (research-edgartools-supplement). The
``EdgartoolsSource`` adapter declares
``SOURCE_ID='edgartools-narrative'``; without this seed row the first
``insert_fact`` for an MD&A or Risk-Factors fact fails the FK
constraint on ``research_facts.source_id``.

PiT class: ``'A'`` — 10-K filings are SEC-timestamped and
backwards-immutable. The per-fact ``effective_from`` carries the
filing's accepted-date so consumers can reason about freshness
without depending on the source-level classification.

Revision ID: 0023_seed_research_source_edgartools_narrative
Revises: 0022_seed_research_source_motley_fool
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_seed_research_source_edgartools_narrative"
down_revision: str | None = "0022_seed_research_source_motley_fool"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SOURCES = [
    {
        "id": "edgartools-narrative",
        "display_name": "SEC EDGAR (10-K narrative via edgartools)",
        "tier": 1,
        "pit_class": "A",
        "metadata": {
            "transport": "edgartools_lib",
            "auth": "ua_identification",
            "fact_kinds": ["sec_text.mdna", "sec_text.risk_factors"],
            "lib_name": "edgartools",
            "lib_license": "MIT",
            "optional_extra": "edgar-narrative",
            "notes": (
                "Supplements the XBRL-only SECEdgarSource (I0) with 10-K "
                "Item 7 (MD&A) + Item 1A (Risk Factors) prose. Lazy import "
                "keeps the base API image small; operators install the "
                "edgar-narrative extra when they want narrative ingest."
            ),
        },
    },
]


def upgrade() -> None:
    bind = op.get_bind()
    timestamp_sql = sa.text("CURRENT_TIMESTAMP" if bind.dialect.name == "sqlite" else "now()")
    meta_ph = ":metadata" if bind.dialect.name == "sqlite" else "CAST(:metadata AS json)"
    for source in _SOURCES:
        op.execute(
            sa.text(
                "INSERT INTO research_sources "
                "(id, display_name, tier, pit_class, enabled, metadata, "
                "created_at, updated_at) "
                "VALUES (:id, :display_name, :tier, :pit_class, :enabled, " + meta_ph + ", "
                f"({timestamp_sql.text}), ({timestamp_sql.text}))"
            ).bindparams(
                enabled=True,
                id=source["id"],
                display_name=source["display_name"],
                tier=source["tier"],
                pit_class=source["pit_class"],
                metadata=json.dumps(source["metadata"]),
            )
        )


def downgrade() -> None:
    for source in _SOURCES:
        op.execute(
            sa.text("DELETE FROM research_sources WHERE id = :id").bindparams(id=source["id"])
        )
