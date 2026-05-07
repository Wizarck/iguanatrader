"""Market-data subsystem (slice T4-followup-market-data).

Decouples bars-fetching from strategy evaluation:

* :class:`MarketDataPort` (in :mod:`iguanatrader.contexts.trading.ports`)
  is the read interface used by the per-symbol propose loops.
* :class:`InMemoryMarketDataAdapter` — test/dev implementation seeded
  with synthetic bars.
* :class:`DBMarketDataAdapter` — production reader; SELECT from
  ``market_data_bars`` populated by the daily ingestion routine.
* :class:`IbAsyncMarketDataIngestor` — production writer; calls IBKR
  ``reqHistoricalDataAsync`` + UPSERT into ``market_data_bars``. Shares
  the broker's ``IbAsyncIBClient`` connection per design Open Question 1.
* :class:`MarketDataIngestionService` — wraps the ingestor with rate
  limiting (``IGUANATRADER_MARKET_DATA_MAX_INVOCATIONS_PER_HOUR``) +
  audit-row writes against ``market_data_sync_audit``.

Errors:

* :class:`MarketDataNotAvailableError` — DB has no bars for the
  (tenant, symbol, timeframe) tuple.
* :class:`MarketDataPacingViolationError` — IBKR refused after retry
  (pacing limit hit).
* :class:`MarketDataRateLimitedError` — operator/CLI exceeded the
  per-hour invocation budget; the audit table records the refusal.
"""

from __future__ import annotations

from typing import ClassVar

from iguanatrader.shared.errors import IguanaError


class MarketDataNotAvailableError(IguanaError):
    """Raised by adapters when no bars exist for the requested key."""

    type_uri: ClassVar[str] = "urn:iguanatrader:error:market-data-not-available"
    default_title: ClassVar[str] = "Market Data Not Available"
    default_status: ClassVar[int] = 404


class MarketDataPacingViolationError(IguanaError):
    """Raised by the IBKR ingestor when a pacing limit was hit twice."""

    type_uri: ClassVar[str] = "urn:iguanatrader:error:market-data-pacing-violation"
    default_title: ClassVar[str] = "Market Data Pacing Violation"
    default_status: ClassVar[int] = 503


class MarketDataRateLimitedError(IguanaError):
    """Raised by :class:`MarketDataIngestionService` when invocation budget exhausted."""

    type_uri: ClassVar[str] = "urn:iguanatrader:error:market-data-rate-limited"
    default_title: ClassVar[str] = "Market Data Rate Limited"
    default_status: ClassVar[int] = 429


__all__ = [
    "MarketDataNotAvailableError",
    "MarketDataPacingViolationError",
    "MarketDataRateLimitedError",
]
