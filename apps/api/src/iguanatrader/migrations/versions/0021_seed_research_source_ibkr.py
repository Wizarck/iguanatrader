"""Seed ``research_sources`` row for the IBKR research adapter.

Slice ``research-ingest-cli-ibkr`` (Ingestion Wave I3). The
``IBKRSource`` adapter declares ``SOURCE_ID='ibkr'`` so this seed row
matches that identifier exactly — without it the first ``insert_fact``
call fails the FK constraint on ``research_facts.source_id``.

Same idempotent INSERT pattern as 0019 (Tier-A) + 0020 (OpenBB).

PiT class: ``'B'`` — the snapshot sub-flow ships data that TWS has
already debounced (price ticks have a millisecond delay vs. exchange
matching engine). Historical bars + contract details are TWS-stamped
but we declare the source uniformly at the more conservative class.
The per-fact ``recorded_from`` column preserves observation time
regardless.

Revision ID: 0021_seed_research_source_ibkr
Revises: 0020_seed_research_source_openbb_sidecar
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_seed_research_source_ibkr"
down_revision: str | None = "0020_seed_research_source_openbb_sidecar"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SOURCES = [
    {
        "id": "ibkr",
        "display_name": "Interactive Brokers (TWS)",
        "tier": 1,
        "pit_class": "B",
        "metadata": {
            "transport": "ib_async",
            "auth": "tws_session",
            "endpoints": [
                "ibkr://snapshot/{symbol}",
                "ibkr://historical/{symbol}",
                "ibkr://contract/{symbol}",
            ],
            "subflows": ["snapshot", "historical", "contract"],
            "license_boundary": "client_library",
            "notes": (
                "Requires a running TWS / IB Gateway session. Client ID "
                "defaults to 17 (distinct from the trading flow's 7) to "
                "avoid collisions on shared TWS instances."
            ),
        },
    },
]


def upgrade() -> None:
    bind = op.get_bind()
    timestamp_sql = sa.text("CURRENT_TIMESTAMP" if bind.dialect.name == "sqlite" else "now()")
    for source in _SOURCES:
        op.execute(
            sa.text(
                "INSERT INTO research_sources "
                "(id, display_name, tier, pit_class, enabled, metadata, "
                "created_at, updated_at) "
                "VALUES (:id, :display_name, :tier, :pit_class, 1, :metadata, "
                f"({timestamp_sql.text}), ({timestamp_sql.text}))"
            ).bindparams(
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
