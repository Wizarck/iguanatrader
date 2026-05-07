"""Market-data ORM models — slice T4-followup-market-data §2.7.

Two tables:

* :class:`MarketDataBar` — historical bars (mutable; UPSERT on
  ``(tenant_id, symbol, timeframe, ts)`` allows IBKR re-ingestion of
  adjusted prices for splits/dividends).
* :class:`MarketDataSyncAudit` — append-only invocation log of every
  ingestion call (daemon-cron + cli-sync + cli-backfill). Used both for
  rate-limiting (count rows in last hour) and ops dashboards.

Append-only enforcement is centralised in
:mod:`iguanatrader.persistence.append_only_listener` (slice 3). Audit
table opts in via ``__tablename_is_append_only__ = True`` +
``__append_only_mutable_columns__: ClassVar[frozenset[str]] = frozenset()``.

Both tables inherit ``__tenant_scoped__ = True`` (default) — the slice-3
``tenant_listener`` injects ``WHERE tenant_id = :ctx_tenant`` on every
SELECT and stamps the column on every INSERT.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from iguanatrader.persistence.base import Base


class MarketDataBar(Base):
    """Historical OHLCV bar (mutable; UPSERT-friendly).

    Mutability rationale: IBKR may ship adjusted prices for splits or
    dividends post-fact. UPSERT on the canonical key
    ``(tenant_id, symbol, timeframe, ts)`` lets the ingestor re-write
    the same row safely without a separate ``adjusted`` flag dance.
    """

    __tablename__ = "market_data_bars"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    timeframe: Mapped[str] = mapped_column(Text, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "symbol",
            "timeframe",
            "ts",
            name="uq_market_data_bars_tenant_id_symbol_timeframe_ts",
        ),
    )


class MarketDataSyncAudit(Base):
    """Audit row for every ingestion invocation (append-only).

    Rate-limit logic in :class:`MarketDataIngestionService` queries this
    table for invocations in the trailing hour. Refused calls also write
    a row with ``status='rate_limited'`` so ops can see who's spamming.
    """

    __tablename__ = "market_data_sync_audit"
    __tablename_is_append_only__ = True
    __append_only_mutable_columns__: ClassVar[frozenset[str]] = frozenset()

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    invoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
    )
    invoked_by: Mapped[str] = mapped_column(Text, nullable=False)
    symbols: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    timeframe: Mapped[str] = mapped_column(Text, nullable=False)
    lookback_bars: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    bars_written: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    duration_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = ["MarketDataBar", "MarketDataSyncAudit"]
