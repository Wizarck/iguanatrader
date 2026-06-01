# mypy: disable-error-code="no-any-unimported,no-untyped-call,attr-defined"
"""IBKR research-data adapter — read-only TWS surface for research_facts.

Slice ``research-ingest-cli-ibkr`` (Ingestion Wave I3). Persists the
three IBKR sub-flows the roadmap calls out:

* **market_snapshot** — forward P/E, beta, market cap, dividend yield,
  52-week high/low. One ``Ticker`` per symbol via
  ``reqTickersAsync`` with ``genericTickList="258"`` (FUND_RATIOS).
* **historical_prices_window** — daily OHLCV bars for the momentum
  pillar. ~5y default via ``reqHistoricalDataAsync``.
* **contract_details** — sector / industry / primary_exchange /
  currency / long_name. Backfills ``symbol_universe`` metadata that
  the manual register-symbol path leaves NULL.

Best-effort per sub-flow: a transient TWS hiccup on one of the three
calls degrades that draft only — the other two still ship. The CLI
wrapping this adapter logs which sub-flows landed vs. were skipped.

PiT classification: row in ``research_sources`` is seeded with
``pit_class='B'`` (snapshot data is the most conservative shape;
historical bars + contract details are TWS-stamped but we declare the
source uniformly). Bitemporal columns on each ``ResearchFactDraft``
carry the per-fetch ``retrieved_at`` so consumers can reason about
freshness regardless of the source-level PiT class.

Deferred-install: ``ib_async`` is lazily imported (same pattern as the
trading-context :class:`IbAsyncIBClient`). The module is importable
without the dep — unit tests inject a mock client. The concrete
:class:`IbAsyncResearchClient` materialises the SDK only when first
used by the CLI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable

from iguanatrader.contexts.research.ports import ResearchFactDraft
from iguanatrader.shared.time import now as utc_now

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


#: Default lookback for the historical bars sub-flow. ~395 calendar
#: days covers the trailing 12-month return + the 252 trading days
#: ``compute_stats`` needs for beta / vol windows with margin.
DEFAULT_HISTORICAL_DURATION_DAYS = 395

#: TWS Generic tick list. ``258`` = FUND_RATIOS (forward P/E, beta,
#: market_cap, dividend_yield, 52w hi/lo, etc — parsed by ib_async
#: into ``Ticker.fundamentalRatios``).
SNAPSHOT_GENERIC_TICKS = "258"

#: Per-sub-flow timeout. TWS occasionally stalls; bound the wait so
#: a single bad fetch does not deadlock the CLI.
SUBFLOW_TIMEOUT_SECONDS = 30.0


@runtime_checkable
class IBKRResearchClient(Protocol):
    """Read-only TWS surface the :class:`IBKRSource` consumes.

    Kept structural so unit tests can inject a plain object with the
    three async methods. The concrete :class:`IbAsyncResearchClient`
    wraps the ``ib_async.IB`` SDK and translates its value objects
    into the dict shapes below.

    Connection lifecycle is owned by the caller: the CLI connects once
    before the first ``fetch_async`` and disconnects after the last.
    """

    async def connect_async(self, host: str, port: int, client_id: int) -> None: ...
    def disconnect(self) -> None: ...

    async def market_snapshot(self, symbol: str) -> dict[str, Any]:
        """Return snapshot ratios keyed by canonical field name.

        Expected keys (each Optional — TWS may not return all of them):
        ``last_price``, ``forward_pe``, ``pe_ratio``, ``beta``,
        ``market_cap``, ``dividend_yield``, ``high_52w``, ``low_52w``.
        """
        ...

    async def historical_bars(
        self,
        symbol: str,
        duration_str: str,
        bar_size: str,
    ) -> list[dict[str, Any]]:
        """Return a list of OHLCV bar dicts with keys
        ``date`` (ISO YYYY-MM-DD), ``open``, ``high``, ``low``,
        ``close``, ``volume``.
        """
        ...

    async def contract_details(self, symbol: str) -> dict[str, Any]:
        """Return contract metadata. Expected keys (each Optional):
        ``long_name``, ``industry``, ``category``, ``subcategory``,
        ``primary_exchange``, ``exchange``, ``currency``, ``con_id``.
        """
        ...


class IBKRSource:
    """``SourcePort``-shaped adapter — TWS → :class:`ResearchFactDraft`.

    Async-first: the primary surface is :meth:`fetch_async` which the
    CLI awaits inside its own event loop. A sync :meth:`fetch` shim
    bridges to ``asyncio.run`` for callers that follow the legacy
    ``SourcePort`` protocol — but the sync path spawns a fresh loop
    each call, so prefer ``fetch_async`` in async callers.
    """

    SOURCE_ID: ClassVar[str] = "ibkr"

    #: Sub-flow identifiers accepted by ``include=``. Used by the CLI
    #: ``--include`` option so the operator can scope a slow fetch.
    SUBFLOWS: ClassVar[frozenset[str]] = frozenset({"snapshot", "historical", "contract"})

    def __init__(
        self,
        client: IBKRResearchClient | None = None,
        *,
        host: str | None = None,
        port: int | None = None,
        client_id: int | None = None,
        enabled: bool | None = None,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self._host = host or os.environ.get("IGUANATRADER_IBKR_HOST", "127.0.0.1")
        self._port = (
            port if port is not None else int(os.environ.get("IGUANATRADER_IBKR_PORT", "7497"))
        )
        # Distinct client_id from the trading flow (default 7) so the
        # research connection never collides with an active paper-trade
        # session sharing the same TWS instance.
        self._client_id = (
            client_id
            if client_id is not None
            else int(os.environ.get("IGUANATRADER_IBKR_RESEARCH_CLIENT_ID", "17"))
        )
        env_flag = os.environ.get("IGUANATRADER_IBKR_RESEARCH_ENABLED", "true").lower()
        self._enabled = enabled if enabled is not None else env_flag != "false"

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    async def fetch_async(
        self,
        symbol: str,
        include: Iterable[str] | None = None,
    ) -> list[ResearchFactDraft]:
        """Pull the requested sub-flows. Best-effort per sub-flow.

        ``include`` defaults to all three. Unknown sub-flow names raise
        ``ValueError`` — the CLI validates input before this method to
        give a user-friendly error.
        """
        if not self._enabled:
            logger.info("research.ibkr.skipped_disabled", extra={"symbol": symbol})
            return []

        requested = self._resolve_include(include)
        client = await self._ensure_client()
        drafts: list[ResearchFactDraft] = []

        if "snapshot" in requested:
            drafts.extend(await self._fetch_snapshot(client, symbol))
        if "historical" in requested:
            drafts.extend(await self._fetch_historical(client, symbol))
        if "contract" in requested:
            drafts.extend(await self._fetch_contract(client, symbol))

        logger.info(
            "research.ibkr.fetch.complete",
            extra={"symbol": symbol, "drafts": len(drafts), "subflows": sorted(requested)},
        )
        return drafts

    def fetch(
        self,
        symbol: str,
        since: datetime | None,
    ) -> Iterable[ResearchFactDraft]:
        """Sync ``SourcePort`` contract — delegates to ``fetch_async``.

        ``since`` is part of the SourcePort contract but is not honoured
        here: TWS snapshot/contract calls always return current state;
        historical bars are constant ~395-day windows. The per-fetch
        ``retrieved_at`` on each draft preserves observation time.
        """
        del since
        return asyncio.run(self.fetch_async(symbol))

    async def close(self) -> None:
        """Disconnect the owned client. No-op when the client was injected."""
        if self._owns_client and self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                logger.warning("research.ibkr.disconnect.failed")
            self._client = None

    # ------------------------------------------------------------------
    # Sub-flow implementations
    # ------------------------------------------------------------------

    async def _fetch_snapshot(
        self,
        client: IBKRResearchClient,
        symbol: str,
    ) -> list[ResearchFactDraft]:
        try:
            payload = await asyncio.wait_for(
                client.market_snapshot(symbol), timeout=SUBFLOW_TIMEOUT_SECONDS
            )
        except Exception as exc:
            logger.warning(
                "research.ibkr.snapshot.failed",
                extra={"symbol": symbol, "error": str(exc)},
            )
            return []

        if not payload:
            return []

        now = utc_now()
        payload_dict = dict(payload)
        return [
            ResearchFactDraft(
                source_id=self.SOURCE_ID,
                fact_kind="ibkr_snapshot",
                effective_from=now,
                recorded_from=now,
                source_url=f"ibkr://snapshot/{symbol}",
                retrieval_method="api",
                retrieved_at=now,
                value_jsonb=payload_dict,
                fact_metadata={"symbol": symbol},
                dedupe_key=f"ibkr:snapshot:{symbol}:{now.date().isoformat()}",
            ).with_payload(json.dumps(payload_dict, default=str).encode("utf-8"))
        ]

    async def _fetch_historical(
        self,
        client: IBKRResearchClient,
        symbol: str,
    ) -> list[ResearchFactDraft]:
        duration_str = f"{DEFAULT_HISTORICAL_DURATION_DAYS} D"
        try:
            bars = await asyncio.wait_for(
                client.historical_bars(symbol, duration_str, "1 day"),
                timeout=SUBFLOW_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            logger.warning(
                "research.ibkr.historical.failed",
                extra={"symbol": symbol, "error": str(exc)},
            )
            return []

        if not bars:
            return []

        # Effective_from = window start (oldest bar). The bitemporal
        # ``recorded_from`` captures fetch time so a later refetch of
        # the same window can be diffed.
        first_iso = str(bars[0].get("date", ""))
        try:
            effective_from = datetime.fromisoformat(first_iso).replace(tzinfo=UTC)
        except ValueError:
            effective_from = utc_now() - timedelta(days=DEFAULT_HISTORICAL_DURATION_DAYS)

        now = utc_now()
        history_payload = {"symbol": symbol, "bars": bars, "bar_size": "1 day"}
        return [
            ResearchFactDraft(
                source_id=self.SOURCE_ID,
                fact_kind="historical_prices_window",
                effective_from=effective_from,
                recorded_from=now,
                source_url=f"ibkr://historical/{symbol}",
                retrieval_method="api",
                retrieved_at=now,
                value_jsonb=history_payload,
                fact_metadata={"symbol": symbol, "duration": duration_str},
                dedupe_key=f"ibkr:historical:{symbol}:{now.date().isoformat()}",
            ).with_payload(json.dumps(history_payload, default=str).encode("utf-8"))
        ]

    async def _fetch_contract(
        self,
        client: IBKRResearchClient,
        symbol: str,
    ) -> list[ResearchFactDraft]:
        try:
            details = await asyncio.wait_for(
                client.contract_details(symbol), timeout=SUBFLOW_TIMEOUT_SECONDS
            )
        except Exception as exc:
            logger.warning(
                "research.ibkr.contract.failed",
                extra={"symbol": symbol, "error": str(exc)},
            )
            return []

        if not details:
            return []

        now = utc_now()
        details_dict = dict(details)
        return [
            ResearchFactDraft(
                source_id=self.SOURCE_ID,
                fact_kind="contract_details",
                effective_from=now,
                recorded_from=now,
                source_url=f"ibkr://contract/{symbol}",
                retrieval_method="api",
                retrieved_at=now,
                value_jsonb=details_dict,
                fact_metadata={"symbol": symbol},
                dedupe_key=f"ibkr:contract:{symbol}",
            ).with_payload(json.dumps(details_dict, default=str).encode("utf-8"))
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_include(self, include: Iterable[str] | None) -> set[str]:
        if include is None:
            return set(self.SUBFLOWS)
        requested = {s.strip().lower() for s in include if s.strip()}
        unknown = requested - self.SUBFLOWS
        if unknown:
            raise ValueError(
                f"Unknown ibkr sub-flow(s): {sorted(unknown)}. " f"Allowed: {sorted(self.SUBFLOWS)}"
            )
        return requested or set(self.SUBFLOWS)

    async def _ensure_client(self) -> IBKRResearchClient:
        if self._client is not None:
            return self._client
        # Lazy materialise the concrete client. Only happens on the
        # first ``fetch_async`` call when no client was injected.
        self._client = IbAsyncResearchClient()
        await self._client.connect_async(self._host, self._port, self._client_id)  # type: ignore[arg-type]
        return self._client


# ---------------------------------------------------------------------------
# Concrete ib_async-backed client
# ---------------------------------------------------------------------------


class IbAsyncResearchClient:
    """Concrete :class:`IBKRResearchClient` over the ``ib_async`` SDK.

    Lazy-imports ``ib_async`` so the module remains importable in
    environments without the dep (CI, dev without TWS). The CLI is the
    only production caller; unit tests inject mocks against the
    :class:`IBKRResearchClient` Protocol instead.

    Smoke-test note: the exact ib_async field names for FUND_RATIOS
    parsing depend on ``ib_async``'s ``Ticker.fundamentalRatios``
    object. We attempt several common attribute names and fall back to
    the canonical generic tick numeric ids. Real-TWS verification is
    expected before production scheduler use (I7).
    """

    def __init__(self) -> None:
        # Bound on connect_async — the IB instance holds the underlying
        # TCP connection.
        self._ib: Any | None = None

    async def connect_async(self, host: str, port: int, client_id: int) -> None:
        from ib_async import IB  # lazy.

        self._ib = IB()
        await self._ib.connectAsync(host, port, clientId=client_id)

    def disconnect(self) -> None:
        if self._ib is not None:
            try:
                self._ib.disconnect()
            finally:
                self._ib = None

    async def market_snapshot(self, symbol: str) -> dict[str, Any]:
        ib = self._require_ib()
        from ib_async import Stock  # lazy.

        contract = Stock(symbol, "SMART", "USD")
        await ib.qualifyContractsAsync(contract)
        tickers = await ib.reqTickersAsync(contract, regulatorySnapshot=False)
        if not tickers:
            return {}
        ticker = tickers[0]

        snapshot: dict[str, Any] = {}
        last = getattr(ticker, "last", None) or getattr(ticker, "marketPrice", None)
        if last is not None:
            snapshot["last_price"] = _to_float(last)
        bid = getattr(ticker, "bid", None)
        ask = getattr(ticker, "ask", None)
        if bid is not None:
            snapshot["bid"] = _to_float(bid)
        if ask is not None:
            snapshot["ask"] = _to_float(ask)
        ratios = getattr(ticker, "fundamentalRatios", None)
        if ratios is not None:
            # ib_async exposes the FUND_RATIOS blob as either a dict or
            # an object with attributes. Probe both shapes.
            for key, alias in _FUND_RATIO_ALIASES.items():
                value = _read_ratio(ratios, key)
                if value is not None:
                    snapshot[alias] = _to_float(value)
        return snapshot

    async def historical_bars(
        self,
        symbol: str,
        duration_str: str,
        bar_size: str,
    ) -> list[dict[str, Any]]:
        ib = self._require_ib()
        from ib_async import Stock  # lazy.

        contract = Stock(symbol, "SMART", "USD")
        await ib.qualifyContractsAsync(contract)
        bars = await ib.reqHistoricalDataAsync(
            contract,
            endDateTime="",  # empty = up to now
            durationStr=duration_str,
            barSizeSetting=bar_size,
            whatToShow="TRADES",
            useRTH=True,
            formatDate=1,
        )
        out: list[dict[str, Any]] = []
        for bar in bars or []:
            out.append(
                {
                    "date": _bar_date_iso(bar),
                    "open": _to_float(bar.open),
                    "high": _to_float(bar.high),
                    "low": _to_float(bar.low),
                    "close": _to_float(bar.close),
                    "volume": _to_float(bar.volume),
                }
            )
        return out

    async def contract_details(self, symbol: str) -> dict[str, Any]:
        ib = self._require_ib()
        from ib_async import Stock  # lazy.

        contract = Stock(symbol, "SMART", "USD")
        details_list = await ib.reqContractDetailsAsync(contract)
        if not details_list:
            return {}
        details = details_list[0]
        c = details.contract
        return {
            "symbol": getattr(c, "symbol", symbol),
            "con_id": getattr(c, "conId", None),
            "exchange": getattr(c, "exchange", None),
            "primary_exchange": getattr(c, "primaryExchange", None),
            "currency": getattr(c, "currency", None),
            "long_name": getattr(details, "longName", None),
            "industry": getattr(details, "industry", None),
            "category": getattr(details, "category", None),
            "subcategory": getattr(details, "subcategory", None),
            "time_zone_id": getattr(details, "timeZoneId", None),
        }

    def _require_ib(self) -> Any:
        if self._ib is None:
            raise RuntimeError(
                "IbAsyncResearchClient.connect_async() must be called before any "
                "data-fetch method."
            )
        return self._ib


# ---------------------------------------------------------------------------
# Translation helpers
# ---------------------------------------------------------------------------


#: Map of ib_async ``FundamentalRatios`` keys (probed by attribute and
#: dict access) to our canonical snake_case names. The aliases mirror
#: what ``compute_stats`` and the brief prompt consume so a snapshot
#: round-trips cleanly into the stat block + LLM citations.
_FUND_RATIO_ALIASES: dict[str, str] = {
    "PEFWD": "forward_pe",
    "PEEXCLXOR": "pe_ratio",
    "PRICE2BK": "price_to_book",
    "BETA": "beta",
    "MKTCAP": "market_cap",
    "YIELD": "dividend_yield",
    "NHIG": "high_52w",
    "NLOW": "low_52w",
}


def _read_ratio(ratios: Any, key: str) -> Any:
    if isinstance(ratios, dict):
        return ratios.get(key)
    # Attribute access — ib_async exposes ratios as a FundamentalRatios
    # value object; the canonical IB names may also appear lowercased.
    for candidate in (key, key.lower(), key.upper()):
        if hasattr(ratios, candidate):
            return getattr(ratios, candidate)
    return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        # ib_async sometimes returns -1 or NaN for "no data".
        if f != f or f == -1.0:  # NaN check
            return None
        return f
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bar_date_iso(bar: Any) -> str:
    raw = getattr(bar, "date", None)
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if hasattr(raw, "isoformat"):
        return str(raw.isoformat())[:10]
    return str(raw)


__all__ = [
    "IBKRResearchClient",
    "IBKRSource",
    "IbAsyncResearchClient",
]
