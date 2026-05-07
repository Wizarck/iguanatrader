"""IBKR market-data ingestor (slice T4-followup-market-data §2.4).

Calls ``IbAsyncIBClient.req_historical_bars`` per symbol + UPSERTs
results into ``market_data_bars``. NOT a :class:`MarketDataPort`
implementation (it writes; doesn't read).

Pacing strategy (per ib_async + IBKR docs):

* :class:`asyncio.Semaphore(1)`: only 1 in-flight request at a time.
* ``0.5s`` sleep between requests: keeps comfortably under the
  ``6 historic-data requests / 2s`` and ``60 / 10min`` IBKR limits.
* 200 daily bars in one request: 1 fetch per symbol (no pagination).

Failure modes:

* Pacing violation from IBKR: caught + retry once after 5s sleep;
  second failure raises :class:`MarketDataPacingViolationError`.
* Connection drop: ``ib_async`` surfaces ``ConnectionError`` — re-raise.
* Unknown contract (delisted ticker): logged + skipped, NO row written.

Connection sharing: per design Open Question 1 (resolved in design.md
§2.4), the ingestor RECEIVES the broker's :class:`IbAsyncIBClient`
instance via constructor injection. Cron schedule (06:00 UTC ingestor
vs 08:00+ UTC propose loops) prevents temporal overlap.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import structlog
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from iguanatrader.contexts.trading.market_data import MarketDataPacingViolationError
from iguanatrader.contexts.trading.market_data.models import MarketDataBar
from iguanatrader.shared.contextvars import session_var, tenant_id_var
from iguanatrader.shared.time import now as utc_now

if TYPE_CHECKING:
    from iguanatrader.contexts.trading.brokers.ib_async_client import IbAsyncIBClient


log = structlog.get_logger("iguanatrader.contexts.trading.market_data.ibkr_ingestor")


_DEFAULT_INTER_REQUEST_SLEEP_MS = 500
_PACING_RETRY_SLEEP_SECONDS = 5.0
_DURATION_BY_TIMEFRAME: dict[str, str] = {
    # IBKR durationStr: "<n> <unit>" where unit ∈ S|D|W|M|Y. For 200
    # daily bars we ask for "200 D" — IBKR returns ≤200 bars depending
    # on holidays; we never ask for more than the timeframe allows.
    "1d": "200 D",
    "1h": "30 D",
    "1m": "5 D",
}
_BAR_SIZE_BY_TIMEFRAME: dict[str, str] = {
    "1d": "1 day",
    "1h": "1 hour",
    "1m": "1 min",
}


@dataclass(slots=True)
class IngestResult:
    """Aggregate stats from a single ``ingest`` call.

    Used both as the ingestor's return value AND as the audit-row
    payload source in :class:`MarketDataIngestionService`.
    """

    successes: list[str] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)
    bars_written: int = 0


class IbAsyncMarketDataIngestor:
    """Fetch historical bars from IBKR + UPSERT into ``market_data_bars``."""

    def __init__(self, *, ib_client: IbAsyncIBClient) -> None:
        self._ib_client = ib_client
        self._semaphore = asyncio.Semaphore(1)

    async def ingest(
        self,
        *,
        symbols: list[str],
        timeframe: str = "1d",
        lookback_bars: int = 200,
    ) -> IngestResult:
        """Fetch + UPSERT per-symbol; returns aggregate :class:`IngestResult`.

        Per-symbol failures are caught + logged + counted in
        ``result.failures``; ingest does NOT abort on a single failure
        (FR isolation: one delisted ticker must not skip the rest of
        the watchlist).
        """
        result = IngestResult()
        sleep_seconds = (
            int(
                os.environ.get(
                    "IGUANATRADER_MARKET_DATA_INTER_REQUEST_SLEEP_MS",
                    _DEFAULT_INTER_REQUEST_SLEEP_MS,
                )
            )
            / 1000.0
        )
        for symbol in symbols:
            async with self._semaphore:
                try:
                    bars = await self._fetch_with_retry(
                        symbol=symbol,
                        timeframe=timeframe,
                        lookback_bars=lookback_bars,
                    )
                    written = await self._upsert(
                        symbol=symbol,
                        timeframe=timeframe,
                        bars=bars,
                    )
                    result.successes.append(symbol)
                    result.bars_written += written
                    log.info(
                        "market_data.ingest.symbol_ok",
                        symbol=symbol,
                        timeframe=timeframe,
                        bars_written=written,
                    )
                except MarketDataPacingViolationError:
                    result.failures.append((symbol, "pacing_violation"))
                    log.error(
                        "market_data.ingest.symbol_pacing_violation",
                        symbol=symbol,
                        timeframe=timeframe,
                    )
                except Exception as exc:
                    result.failures.append((symbol, str(exc)))
                    log.warning(
                        "market_data.ingest.symbol_failed",
                        symbol=symbol,
                        timeframe=timeframe,
                        error=str(exc),
                    )
                await asyncio.sleep(sleep_seconds)
        return result

    async def _fetch_with_retry(
        self,
        *,
        symbol: str,
        timeframe: str,
        lookback_bars: int,
    ) -> list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, int]]:
        """Fetch with one pacing-retry. Returns rows ready for UPSERT."""
        try:
            return await self._fetch(
                symbol=symbol,
                timeframe=timeframe,
                lookback_bars=lookback_bars,
            )
        except Exception as exc:
            if "pacing" not in str(exc).lower():
                raise
            log.warning(
                "market_data.ingest.pacing_retry_after_sleep",
                symbol=symbol,
                sleep_seconds=_PACING_RETRY_SLEEP_SECONDS,
            )
            await asyncio.sleep(_PACING_RETRY_SLEEP_SECONDS)
            try:
                return await self._fetch(
                    symbol=symbol,
                    timeframe=timeframe,
                    lookback_bars=lookback_bars,
                )
            except Exception as retry_exc:
                raise MarketDataPacingViolationError(
                    detail=(
                        f"IBKR pacing violation for symbol={symbol!r} "
                        f"persisted after retry: {retry_exc}"
                    ),
                ) from retry_exc

    async def _fetch(
        self,
        *,
        symbol: str,
        timeframe: str,
        lookback_bars: int,
    ) -> list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, int]]:
        duration_str = _DURATION_BY_TIMEFRAME.get(timeframe, "200 D")
        bar_size = _BAR_SIZE_BY_TIMEFRAME.get(timeframe, "1 day")
        raw_bars = await self._ib_client.req_historical_bars(
            symbol=symbol,
            duration_str=duration_str,
            bar_size=bar_size,
        )
        # ib_async returns BarData objects with .date, .open, .high, .low, .close, .volume.
        rows: list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, int]] = []
        for bar in list(raw_bars)[-lookback_bars:]:
            bar_date = bar.date
            if not isinstance(bar_date, datetime):
                bar_date = datetime.combine(bar_date, datetime.min.time())
            rows.append(
                (
                    bar_date,
                    Decimal(str(bar.open)),
                    Decimal(str(bar.high)),
                    Decimal(str(bar.low)),
                    Decimal(str(bar.close)),
                    int(bar.volume),
                )
            )
        return rows

    async def _upsert(
        self,
        *,
        symbol: str,
        timeframe: str,
        bars: list[tuple[datetime, Decimal, Decimal, Decimal, Decimal, int]],
    ) -> int:
        """UPSERT rows on ``(tenant_id, symbol, timeframe, ts)`` conflict.

        Uses sqlite-dialect ``insert(...).on_conflict_do_update`` (CI +
        local dev run sqlite). Postgres deployment will use the same
        dialect-conditional pattern via ``sqlalchemy.dialects.postgresql``
        when needed; v1 ships sqlite + postgres-via-same-syntax.
        """
        if not bars:
            return 0
        session = session_var.get()
        if session is None:
            raise LookupError("session_var not set; ingestor cannot UPSERT market_data_bars.")
        tenant_id = tenant_id_var.get()
        if tenant_id is None:
            raise LookupError("tenant_id_var not set; ingestor cannot UPSERT market_data_bars.")
        fetched = utc_now()
        rows: list[dict[str, object]] = [
            {
                "id": str(uuid4()),
                "tenant_id": str(tenant_id),
                "symbol": symbol,
                "timeframe": timeframe,
                "ts": ts,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "source": "ibkr",
                "fetched_at": fetched,
            }
            for (ts, open_, high, low, close, volume) in bars
        ]
        stmt = sqlite_insert(MarketDataBar).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["tenant_id", "symbol", "timeframe", "ts"],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "source": stmt.excluded.source,
                "fetched_at": stmt.excluded.fetched_at,
            },
        )
        await session.execute(stmt)
        await session.flush()
        return len(rows)


__all__ = ["IbAsyncMarketDataIngestor", "IngestResult"]
