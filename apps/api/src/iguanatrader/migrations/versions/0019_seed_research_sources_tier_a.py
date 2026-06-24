"""Seed ``research_sources`` rows for Tier-A adapters.

Slice ``research-ingest-cli-sec-edgar`` (Ingestion Wave I0). Adapters
for SEC EDGAR, FRED, BEA, and BLS were built in slice R2 but the
corresponding ``research_sources`` rows were never seeded — the only
seed (migration ``0010_research_sources_tier_b_c``) covers Tier-B/C.
That meant any ``insert_fact`` from a Tier-A adapter would have failed
the FK constraint on ``source_id``. This migration closes that gap so
the new ``iguanatrader research ingest sec-edgar`` (and future
``fred`` / ``bea`` / ``bls``) CLI commands can persist.

Mirrors the ``0010_research_sources_tier_b_c`` pattern: raw INSERTs
inside an idempotent loop. The downgrade removes only the rows added
here; pre-existing rows (if a future migration ever re-adds these
ids) would be unaffected by the WHERE-id clause.

Revision ID: 0019_seed_research_sources_tier_a
Revises: 0018_trade_journal_narrative
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_seed_research_sources_tier_a"
down_revision: str | None = "0018_trade_journal_narrative"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SOURCES = [
    {
        "id": "sec_edgar",
        "display_name": "SEC EDGAR",
        "tier": 1,
        "pit_class": "A",
        "metadata": {
            "rate_limit_config": {"requests_per_second": 10},
            "endpoints": ["/submissions", "/companyfacts", "/company_tickers"],
            "auth": "user_agent",
            "license": "us_public_domain",
        },
    },
    {
        "id": "fred",
        "display_name": "FRED (Federal Reserve Economic Data)",
        "tier": 1,
        "pit_class": "A",
        "metadata": {
            "rate_limit_config": {"requests_per_minute": 120},
            "endpoints": ["/series/observations"],
            "auth": "api_key",
            "alfred_vintage_aware": True,
            "license": "us_public_domain_attribution",
        },
    },
    {
        "id": "bea",
        "display_name": "BEA (Bureau of Economic Analysis)",
        "tier": 1,
        "pit_class": "A",
        "metadata": {
            "rate_limit_config": {"requests_per_hour": 1000},
            "endpoints": ["/api/data"],
            "auth": "api_key",
            "license": "us_public_domain",
        },
    },
    {
        "id": "bls",
        "display_name": "BLS (Bureau of Labor Statistics)",
        "tier": 1,
        "pit_class": "A",
        "metadata": {
            "rate_limit_config": {"requests_per_day": 500},
            "endpoints": ["/publicAPI/v2/timeseries/data"],
            "auth": "api_key",
            "license": "us_public_domain",
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
