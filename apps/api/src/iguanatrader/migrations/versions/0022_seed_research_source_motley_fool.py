"""Seed ``research_sources`` row for the Motley Fool transcript adapter.

Slice ``I5`` (research-transcripts-fool-scraper). The
``MotleyFoolTranscriptSource`` adapter declares ``SOURCE_ID='motley-fool'``;
without this seed row the first ``insert_fact`` call fails the FK
constraint on ``research_facts.source_id``.

PiT class: ``'B'`` — transcripts are snapshot-published (delayed
relative to the live call) and the page can be retroactively edited,
so we declare a non-PiT-safe class. The per-fact ``recorded_from``
preserves true observation time.

Revision ID: 0022_seed_research_source_motley_fool
Revises: 0021_seed_research_source_ibkr
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_seed_research_source_motley_fool"
down_revision: str | None = "0021_seed_research_source_ibkr"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SOURCES = [
    {
        "id": "motley-fool",
        "display_name": "The Motley Fool (earnings call transcripts)",
        "tier": 2,
        "pit_class": "B",
        "metadata": {
            "transport": "web_scrape",
            "auth": "none",
            "endpoints": [
                "https://www.fool.com/earnings/call-transcripts/{year}/{month}/{day}/{slug}/",
            ],
            "rate_limit_config": {"requests_per_second": 0.33, "note": "polite 1 req / 3s"},
            "scraping_tier_max": 1,
            "license_boundary": "fair_use_excerpt",
            "opt_in_env": "ENABLE_FOOL_SCRAPER",
            "notes": (
                "Disabled by default. Set ENABLE_FOOL_SCRAPER=true to enable. "
                "ToS-fragile — a single UI redesign or IP block can break the "
                "adapter; treat partial unavailability as expected and keep "
                "the rest of the pipeline running."
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
