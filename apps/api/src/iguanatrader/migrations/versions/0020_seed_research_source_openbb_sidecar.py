"""Seed ``research_sources`` row for the OpenBB sidecar adapter.

Slice ``openbb-sidecar-in-mvp-compose`` (Ingestion Wave I2). The
``OpenBBSidecarSource`` adapter declares ``SOURCE_ID="openbb-sidecar"``
(with hyphen, mirroring the URL path) so this seed row matches that
identifier exactly — without it the first ``insert_fact`` call fails
the FK constraint on ``research_facts.source_id``.

Same pattern as migrations 0010 (Tier-B/C) + 0019 (Tier-A): raw INSERT
inside an idempotent loop; downgrade removes only the rows added here.

Revision ID: 0020_seed_research_source_openbb_sidecar
Revises: 0019_seed_research_sources_tier_a
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_seed_research_source_openbb_sidecar"
down_revision: str | None = "0019_seed_research_sources_tier_a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SOURCES = [
    {
        "id": "openbb-sidecar",
        "display_name": "OpenBB Platform (sidecar)",
        "tier": 1,
        "pit_class": "B",
        "metadata": {
            "rate_limit_config": {"requests_per_minute": 60},
            "endpoints": [
                "/v1/equity/fundamentals/{symbol}",
                "/v1/equity/ratings/{symbol}",
                "/v1/equity/esg/{symbol}",
                "/v1/economy/macro/{indicator}",
            ],
            "auth": "none",
            "transport": "http_loopback",
            "license_boundary": "agpl_isolated",
            "default_provider": "yfinance",
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
