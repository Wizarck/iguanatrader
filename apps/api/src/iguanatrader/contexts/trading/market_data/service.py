"""MarketDataIngestionService — orchestrates ingestor + rate-limit + audit.

Per slice T4-followup-market-data §2.5: every ingestion invocation
(daemon-cron, cli-sync, cli-backfill) goes through ``sync(...)`` which:

1. Counts audit rows in the trailing hour for the current tenant.
2. If count >= ``IGUANATRADER_MARKET_DATA_MAX_INVOCATIONS_PER_HOUR``:
   writes a ``status='rate_limited'`` audit row + raises
   :class:`MarketDataRateLimitedError` without calling IBKR.
3. Otherwise calls the ingestor + writes the corresponding audit row
   (``status='success'|'partial'|'failed'``) on completion.

Rate-limit budget covers daemon + CLI invocations under one tenant.
Daemon's daily cron consumes 1/hour; CLI users get
``MAX_INVOCATIONS_PER_HOUR - 1`` free invocations/hour effectively.
"""

from __future__ import annotations

import os
import time
from datetime import timedelta
from typing import Literal

import structlog

from iguanatrader.contexts.trading.market_data import MarketDataRateLimitedError
from iguanatrader.contexts.trading.market_data.ibkr_ingestor import (
    IbAsyncMarketDataIngestor,
    IngestResult,
)
from iguanatrader.contexts.trading.market_data.repository import (
    MarketDataSyncAuditRepository,
)
from iguanatrader.shared.time import now as utc_now

log = structlog.get_logger("iguanatrader.contexts.trading.market_data.service")


_DEFAULT_MAX_INVOCATIONS_PER_HOUR = 10


def _get_max_invocations_per_hour() -> int:
    raw = os.environ.get(
        "IGUANATRADER_MARKET_DATA_MAX_INVOCATIONS_PER_HOUR",
        str(_DEFAULT_MAX_INVOCATIONS_PER_HOUR),
    )
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_MAX_INVOCATIONS_PER_HOUR


InvokedBy = Literal["daemon-cron", "cli-sync", "cli-backfill"]


class MarketDataIngestionService:
    """Domain service wrapping the ingestor with rate-limit + audit."""

    def __init__(
        self,
        *,
        ingestor: IbAsyncMarketDataIngestor,
        audit_repo: MarketDataSyncAuditRepository,
    ) -> None:
        self._ingestor = ingestor
        self._audit_repo = audit_repo

    async def sync(
        self,
        *,
        symbols: list[str],
        timeframe: str = "1d",
        lookback_bars: int = 200,
        invoked_by: InvokedBy,
    ) -> IngestResult:
        """Audit-wrapped ingestor call with rate-limit guard."""
        max_invocations = _get_max_invocations_per_hour()
        recent_count = await self._audit_repo.count_invocations_since(
            since=utc_now() - timedelta(hours=1),
        )
        if recent_count >= max_invocations:
            await self._audit_repo.write_audit_row(
                invoked_by=invoked_by,
                symbols=symbols,
                timeframe=timeframe,
                lookback_bars=lookback_bars,
                status="rate_limited",
                bars_written=0,
                duration_ms=0,
                error=(
                    f"Exceeded {max_invocations} invocations/hour "
                    f"(found {recent_count} in trailing hour)."
                ),
            )
            log.warning(
                "market_data.sync.rate_limited",
                invoked_by=invoked_by,
                recent_count=recent_count,
                max_invocations=max_invocations,
            )
            raise MarketDataRateLimitedError(
                detail=(
                    f"Rate limit exceeded: {recent_count}/"
                    f"{max_invocations} invocations in the last hour. "
                    "Wait + retry."
                ),
            )

        start = time.monotonic()
        try:
            result = await self._ingestor.ingest(
                symbols=symbols,
                timeframe=timeframe,
                lookback_bars=lookback_bars,
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            await self._audit_repo.write_audit_row(
                invoked_by=invoked_by,
                symbols=symbols,
                timeframe=timeframe,
                lookback_bars=lookback_bars,
                status="failed",
                bars_written=0,
                duration_ms=duration_ms,
                error=str(exc),
            )
            log.error(
                "market_data.sync.failed",
                invoked_by=invoked_by,
                error=str(exc),
                duration_ms=duration_ms,
            )
            raise
        duration_ms = int((time.monotonic() - start) * 1000)
        status = "success" if not result.failures else "partial"
        await self._audit_repo.write_audit_row(
            invoked_by=invoked_by,
            symbols=symbols,
            timeframe=timeframe,
            lookback_bars=lookback_bars,
            status=status,
            bars_written=result.bars_written,
            duration_ms=duration_ms,
            error=None,
        )
        log.info(
            "market_data.sync.complete",
            invoked_by=invoked_by,
            status=status,
            successes=len(result.successes),
            failures=len(result.failures),
            bars_written=result.bars_written,
            duration_ms=duration_ms,
        )
        return result


__all__ = ["InvokedBy", "MarketDataIngestionService"]
