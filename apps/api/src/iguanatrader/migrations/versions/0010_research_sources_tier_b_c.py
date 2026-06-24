"""Seed ``research_sources`` rows for slice R3 Tier-B + Tier-C adapters.

Per slice R3: each :class:`SourcePort` adapter persists facts under a
``source_id`` that joins ``research_sources``. R3 ships 5 Tier-1
webfetch adapters (Finnhub / GDELT / OpenFDA / WGI / V-Dem); this
migration seeds the corresponding rows so the FK constraint is
satisfied at first insert.

Migration slot deviation: tasks.md called for ``0004``. R2 + R5 took
``0008`` + ``0009`` before R3 applied; R3 ships as ``0010`` with
``down_revision='0009_research_audit_trail'``. Documented in retro per
the running migration-slot-collision pattern (now 4 slices in a row).

Revision ID: 0010_research_sources_tier_b_c
Revises: 0009_research_audit_trail
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_research_sources_tier_b_c"
down_revision: str | None = "0009_research_audit_trail"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ----------------------------------------------------------------------
# Source rows seeded by this migration
# ----------------------------------------------------------------------

_SOURCES = [
    {
        "id": "finnhub",
        "display_name": "Finnhub",
        "tier": 1,  # Tier-1 in the scrape ladder (httpx/JSON API).
        "pit_class": "B",
        "metadata": {
            "rate_limit_config": {"requests_per_minute": 60},
            "endpoints": ["/company-news", "/calendar/earnings"],
            "auth": "api_key",
        },
    },
    {
        "id": "gdelt",
        "display_name": "GDELT Project",
        "tier": 1,
        "pit_class": "B",
        "metadata": {
            "rate_limit_config": {"requests_per_minute": 15},
            "refresh_window_minutes": 15,
            "auth": "none",
        },
    },
    {
        "id": "openfda",
        "display_name": "OpenFDA",
        "tier": 1,
        "pit_class": "B",
        "metadata": {
            "rate_limit_config": {"requests_per_minute": 240},
            "endpoints": ["/drug/drugsfda.json"],
            "auth": "none",
        },
    },
    {
        "id": "wgi_world_bank",
        "display_name": "World Bank Worldwide Governance Indicators",
        "tier": 1,
        "pit_class": "C",
        "metadata": {
            "rate_limit_config": {"requests_per_minute": 60},
            "auth": "none",
            "annual_release": True,
        },
    },
    {
        "id": "vdem",
        "display_name": "V-Dem Varieties of Democracy",
        "tier": 1,
        "pit_class": "C",
        "metadata": {
            "rate_limit_config": {"requests_per_minute": 60},
            "auth": "none",
            "annual_release": True,
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
