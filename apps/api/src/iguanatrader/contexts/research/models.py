"""Research bounded-context ORM models — bitemporal facts, briefs, catalogue.

Per data-model §3.7 + ADR-014 + design D1-D5:

* :class:`ResearchSource` — cross-tenant catalogue (``__tenant_scoped__ = False``).
  No ``tenant_id`` column. Every tenant queries the same row.
* :class:`SymbolUniverse` — per-tenant, mutable. The "what symbols this tenant
  cares about" table.
* :class:`WatchlistConfig` — per-tenant, mutable. Drives ingestion schedule +
  methodology selection.
* :class:`ResearchFact` — per-tenant, append-only, BITEMPORAL. The cornerstone.
  Four timestamp columns (effective × recorded) + provenance NOT NULL set +
  hybrid-payload XOR + value-polymorphism CHECK. Updates blocked at L1
  (slice-3 ORM listener) and L2 (per-table BEFORE UPDATE/DELETE triggers
  emitted by migration ``0003_research_tables``); the only permitted UPDATE
  is the narrow ``recorded_to: NULL → :ts`` supersession path.
* :class:`ResearchBrief` — per-tenant, append-only, versioned. ``version``
  monotonically increases per ``(tenant_id, symbol_universe_id)`` per design
  D5; uniqueness enforced by index + retry-on-IntegrityError in R5.
* :class:`CorporateEvent` — per-tenant, append-only.
* :class:`AnalystRating` — per-tenant, append-only.

Design notes:

* All UUID PK/FK columns use SQLAlchemy's :class:`Uuid` type per slice-3
  precedent (gotcha #21 — ORM-driven CREATE TABLE produces ``CHAR(32)``;
  Alembic migration declares ``CHAR(36)`` but the listener compares
  :class:`UUID` instances on both sides so the storage shape is invisible
  at the ORM boundary).
* JSON columns use cross-dialect :class:`JSON` (per data-model §7c open
  question — Postgres v1.5 can swap in JSONB without an ORM-level change).
* The ``raw_payload_inline`` column accepts JSON-coercible values OR raw
  text; we declare it as :class:`JSON` so JSONB queryability comes for free
  on Postgres in v1.5.
* No ``__init__`` overrides; SQLAlchemy generates them. Pydantic
  :class:`ResearchFactDraft` (in ``ports.py``) is the input-validation
  layer adapters use.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CHAR,
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from iguanatrader.persistence.base import Base


class ResearchSource(Base):
    """Cross-tenant source catalogue (``sec_edgar``, ``fred``, ``finnhub``, …).

    Per data-model §3.7 note: ``research_sources`` is shared across tenants
    (catalogue, not per-tenant data). ``__tenant_scoped__ = False`` so the
    slice-3 tenant listener does NOT inject ``tenant_id`` filter on SELECTs;
    the table has no ``tenant_id`` column at all.
    """

    __tablename__ = "research_sources"
    __tenant_scoped__ = False

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    pit_class: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="1",
    )
    last_health_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    source_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    __table_args__ = (
        CheckConstraint("tier IN (1,2,3,4)", name="tier_allowed"),
        CheckConstraint("pit_class IN ('A','B','C')", name="pit_class_allowed"),
    )


class SymbolUniverse(Base):
    """Per-tenant symbol catalogue. Mutable.

    ``(tenant_id, symbol, exchange)`` is unique per data-model §3.7.
    """

    __tablename__ = "symbol_universe"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    exchange: Mapped[str] = mapped_column(Text, nullable=False)
    sector: Mapped[str | None] = mapped_column(Text, nullable=True)
    industry: Mapped[str | None] = mapped_column(Text, nullable=True)
    market_cap_bucket: Mapped[str | None] = mapped_column(Text, nullable=True)
    ipo_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delisted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "symbol",
            "exchange",
            name="uq_symbol_universe_tenant_id_symbol_exchange",
        ),
        Index(
            "ix_symbol_universe_tenant_id_sector",
            "tenant_id",
            "sector",
        ),
        CheckConstraint(
            "market_cap_bucket IS NULL OR market_cap_bucket IN "
            "('mega','large','mid','small','micro')",
            name="market_cap_bucket_allowed",
        ),
    )


class WatchlistConfig(Base):
    """Per-tenant ingestion + brief-refresh schedule. Mutable."""

    __tablename__ = "watchlist_configs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    symbol_universe_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("symbol_universe.id", ondelete="RESTRICT"),
        nullable=False,
    )
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    methodology: Mapped[str] = mapped_column(Text, nullable=False)
    methodology_params: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    brief_refresh_schedule: Mapped[str] = mapped_column(Text, nullable=False)
    brief_refresh_cron: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="1",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "symbol_universe_id",
            name="uq_watchlist_configs_tenant_id_symbol_universe_id",
        ),
        Index(
            "ix_watchlist_configs_tenant_id_tier",
            "tenant_id",
            "tier",
        ),
        CheckConstraint(
            "tier IN ('primary','secondary')",
            name="tier_allowed",
        ),
        CheckConstraint(
            "methodology IN ('three_pillar','canslim','magic_formula',"
            "'qarp','multi_factor')",
            name="methodology_allowed",
        ),
        CheckConstraint(
            "brief_refresh_schedule IN ('daily','weekly','manual')",
            name="brief_refresh_schedule_allowed",
        ),
    )


class ResearchFact(Base):
    """Bitemporal append-only research fact (per ADR-014 + design D1-D4).

    See module docstring + design.md D1/D2/D3/D4 for the full constraint
    set. The L1 listener (slice 3) blocks ORM UPDATE/DELETE; the L2
    triggers (migration ``0003``) block raw SQL with the narrow
    ``recorded_to: NULL → :ts`` exception.
    """

    __tablename__ = "research_facts"
    __tablename_is_append_only__ = True

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("research_sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    symbol_universe_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("symbol_universe.id", ondelete="RESTRICT"),
        nullable=True,
    )
    fact_kind: Mapped[str] = mapped_column(Text, nullable=False)

    # Polymorphic value columns — at least one MUST be non-NULL.
    value_numeric: Mapped[Decimal | None] = mapped_column(
        Numeric(28, 12),
        nullable=True,
    )
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_jsonb: Mapped[Any | None] = mapped_column(JSON, nullable=True)

    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str | None] = mapped_column(CHAR(3), nullable=True)

    # Bitemporal axes.
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    recorded_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    recorded_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Provenance.
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    retrieval_method: Mapped[str] = mapped_column(Text, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # Hybrid payload storage (per design D3).
    raw_payload_inline: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    raw_payload_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload_sha256: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    raw_payload_size_bytes: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4),
        nullable=True,
    )
    fact_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    __table_args__ = (
        # Provenance — defence in depth (NOT NULL above + CHECK below).
        CheckConstraint(
            "length(source_url) > 0",
            name="source_url_not_empty",
        ),
        CheckConstraint(
            "retrieval_method IN ('api','scrape','manual','llm')",
            name="retrieval_method_allowed",
        ),
        # Temporal sanity (per design D2).
        CheckConstraint(
            "effective_from <= COALESCE(effective_to, '9999-12-31')",
            name="effective_temporal_sanity",
        ),
        CheckConstraint(
            "recorded_from <= COALESCE(recorded_to, '9999-12-31')",
            name="recorded_temporal_sanity",
        ),
        # At least one value field set.
        CheckConstraint(
            "value_numeric IS NOT NULL OR value_text IS NOT NULL "
            "OR value_jsonb IS NOT NULL",
            name="at_least_one_value",
        ),
        # Hybrid-payload CHECK constraints (per design D3).
        CheckConstraint(
            "(raw_payload_inline IS NULL) <> (raw_payload_path IS NULL)",
            name="payload_xor_inline_path",
        ),
        CheckConstraint(
            "raw_payload_path IS NULL OR raw_payload_sha256 IS NOT NULL",
            name="payload_path_requires_sha256",
        ),
        CheckConstraint(
            "raw_payload_size_bytes IS NULL OR raw_payload_size_bytes < 16384 "
            "OR raw_payload_path IS NOT NULL",
            name="payload_size_tier_consistency",
        ),
        CheckConstraint(
            "raw_payload_size_bytes IS NULL OR raw_payload_size_bytes >= 0",
            name="payload_size_nonneg",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_unit_interval",
        ),
        # Indexes per data-model §3.7.
        Index(
            "ix_research_facts_tenant_id_symbol_universe_id_fact_kind",
            "tenant_id",
            "symbol_universe_id",
            "fact_kind",
        ),
        Index(
            "ix_research_facts_tenant_id_fact_kind_effective_from",
            "tenant_id",
            "fact_kind",
            "effective_from",
        ),
        Index(
            "ix_research_facts_tenant_id_recorded_from",
            "tenant_id",
            "recorded_from",
        ),
        Index(
            "ix_research_facts_source_id",
            "source_id",
        ),
    )


class ResearchBrief(Base):
    """Append-only versioned research brief (per design D5).

    ``version`` is monotonic per ``(tenant_id, symbol_universe_id)`` —
    enforced by the unique constraint + R5's retry-on-IntegrityError
    insertion logic.
    """

    __tablename__ = "research_briefs"
    __tablename_is_append_only__ = True

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    symbol_universe_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("symbol_universe.id", ondelete="RESTRICT"),
        nullable=False,
    )
    watchlist_config_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("watchlist_configs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    methodology: Mapped[str] = mapped_column(Text, nullable=False)
    thesis_text: Mapped[str] = mapped_column(Text, nullable=False)
    score_overall: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4),
        nullable=True,
    )
    score_components: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    citations: Mapped[Any] = mapped_column(JSON, nullable=False)
    audit_trail: Mapped[Any] = mapped_column(JSON, nullable=False)
    llm_provider: Mapped[str] = mapped_column(Text, nullable=False)
    llm_model: Mapped[str] = mapped_column(Text, nullable=False)
    llm_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    llm_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    llm_cache_hit_tokens: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    partial: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="0",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "symbol_universe_id",
            "version",
            name="uq_research_briefs_tenant_id_symbol_universe_id_version",
        ),
        Index(
            "ix_research_briefs_tenant_id_symbol_universe_id_created_at",
            "tenant_id",
            "symbol_universe_id",
            "created_at",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "methodology IN ('three_pillar','canslim','magic_formula',"
            "'qarp','multi_factor')",
            name="methodology_allowed",
        ),
        CheckConstraint(
            "score_overall IS NULL OR (score_overall >= 0 AND score_overall <= 1)",
            name="score_unit_interval",
        ),
        CheckConstraint(
            "llm_input_tokens >= 0",
            name="input_tokens_nonneg",
        ),
        CheckConstraint(
            "llm_output_tokens >= 0",
            name="output_tokens_nonneg",
        ),
        CheckConstraint(
            "llm_cache_hit_tokens >= 0",
            name="cache_hit_tokens_nonneg",
        ),
    )


class CorporateEvent(Base):
    """Append-only corporate event (earnings, dividends, splits, M&A, FDA)."""

    __tablename__ = "corporate_events"
    __tablename_is_append_only__ = True

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    symbol_universe_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("symbol_universe.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_kind: Mapped[str] = mapped_column(Text, nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    payload: Mapped[Any] = mapped_column(JSON, nullable=False)
    source_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("research_sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    __table_args__ = (
        Index(
            "ix_corporate_events_tenant_id_symbol_universe_id_event_date",
            "tenant_id",
            "symbol_universe_id",
            "event_date",
        ),
        Index(
            "ix_corporate_events_tenant_id_event_kind_event_date",
            "tenant_id",
            "event_kind",
            "event_date",
        ),
        CheckConstraint(
            "event_kind IN ('earnings_release','ex_dividend','split',"
            "'merger_announcement','fda_approval','spinoff','tender_offer',"
            "'recall','other')",
            name="event_kind_allowed",
        ),
        CheckConstraint(
            "length(source_url) > 0",
            name="source_url_not_empty",
        ),
    )


class AnalystRating(Base):
    """Append-only analyst rating snapshot."""

    __tablename__ = "analyst_ratings"
    __tablename_is_append_only__ = True

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    symbol_universe_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("symbol_universe.id", ondelete="RESTRICT"),
        nullable=False,
    )
    firm_name: Mapped[str] = mapped_column(Text, nullable=False)
    analyst_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    rating: Mapped[str] = mapped_column(Text, nullable=False)
    previous_rating: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_target: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 8),
        nullable=True,
    )
    price_target_currency: Mapped[str | None] = mapped_column(
        CHAR(3),
        nullable=True,
        server_default="'USD'",
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("research_sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    __table_args__ = (
        Index(
            "ix_analyst_ratings_tenant_id_symbol_universe_id_published_at",
            "tenant_id",
            "symbol_universe_id",
            "published_at",
        ),
        Index(
            "ix_analyst_ratings_tenant_id_firm_name_published_at",
            "tenant_id",
            "firm_name",
            "published_at",
        ),
        CheckConstraint(
            "rating IN ('strong_buy','buy','hold','sell',"
            "'strong_sell','withdrawn')",
            name="rating_allowed",
        ),
        CheckConstraint(
            "length(source_url) > 0",
            name="source_url_not_empty",
        ),
    )


__all__ = [
    "AnalystRating",
    "CorporateEvent",
    "ResearchBrief",
    "ResearchFact",
    "ResearchSource",
    "SymbolUniverse",
    "WatchlistConfig",
]
