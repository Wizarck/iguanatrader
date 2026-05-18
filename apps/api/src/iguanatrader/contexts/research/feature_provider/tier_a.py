"""Tier-A feature provider — native point-in-time sources (slice R5 D2, R3 YoY + returns).

Tier-A feature names map to fact_kinds R2 ingested:

* ``eps_diluted`` <- ``sec_xbrl.us-gaap.EarningsPerShareDiluted``
* ``revenue`` <- ``sec_xbrl.us-gaap.Revenues`` (with ASC 606 / legacy
  fallback chain — see ``_REVENUE_FACT_KINDS`` for the full list)
* ``cpi_yoy`` <- ``fred.CPIAUCSL`` (year-over-year).
* ``unemployment_rate`` <- ``fred.UNRATE``.
* ``fed_funds_rate`` <- ``fred.DFF``.

Slice R3 adds derived features computed from a window of XBRL or price
facts:

* ``eps_growth_yoy`` — (latest_FY EPS - prior_FY EPS) / |prior_FY EPS|.
* ``revenue_growth_yoy`` — same for Revenues.
* ``return_3m`` — (close_now - close_~90d_ago) / close_~90d_ago.
* ``return_12m`` — (close_now - close_~365d_ago) / close_~365d_ago.
* ``relative_strength`` — 12-month return delta vs SPY benchmark, mapped
  to ``[0, 1]`` via ``0.5 + (ret_sym - ret_spy) / 2`` then clipped.

Restatements of the same fiscal year (10-K/A) are collapsed by taking
the latest ``recorded_from`` per ``effective_from`` date. Price windows
(``historical_prices_window`` fact_kind) come from the OpenBB sidecar
as one fact per refresh — bars list lives in ``value_jsonb["bars"]``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, DivisionByZero, InvalidOperation
from typing import TYPE_CHECKING, Any
from uuid import UUID

from iguanatrader.contexts.research.feature_provider.base import (
    FeatureBundle,
    FeatureValue,
)
from iguanatrader.shared.time import now as utc_now

if TYPE_CHECKING:
    from iguanatrader.contexts.research.models import ResearchFact
    from iguanatrader.contexts.research.repository import ResearchRepository


# Revenue XBRL tag fallback chain. ``us-gaap.Revenues`` is the canonical
# concept but many companies tag revenue under more specific concepts:
#   * ``RevenueFromContractWithCustomerExcludingAssessedTax`` — ASC 606
#     adopters (post-2018, the majority of large-cap tech including AMD).
#   * ``SalesRevenueNet`` — legacy filers pre-ASC 606.
#   * ``SalesRevenueGoodsNet`` — companies that distinguish goods vs.
#     services (AMD, Intel).
# The repository's ``facts_history_by_kinds`` query returns matches from
# any of the listed kinds; the YoY computation then dedupes by period so
# a company that switched tags between fiscal years still compares
# apples-to-apples within each tag's coverage window.
_REVENUE_FACT_KINDS: tuple[str, ...] = (
    "sec_xbrl.us-gaap.Revenues",
    "sec_xbrl.us-gaap.RevenueFromContractWithCustomerExcludingAssessedTax",
    "sec_xbrl.us-gaap.SalesRevenueNet",
    "sec_xbrl.us-gaap.SalesRevenueGoodsNet",
)

# Native-fact mappings — feature name → ordered fact_kind candidates.
_FACT_KIND_BY_FEATURE: dict[str, tuple[str, ...]] = {
    "eps_diluted": ("sec_xbrl.us-gaap.EarningsPerShareDiluted",),
    "revenue": _REVENUE_FACT_KINDS,
    "cpi_yoy": ("fred.CPIAUCSL",),
    "unemployment_rate": ("fred.UNRATE",),
    "fed_funds_rate": ("fred.DFF",),
}

# Derived YoY features — (feature_name, source_fact_kinds). Multiple
# source kinds let one feature draw from a fallback chain.
_YOY_DERIVATIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("eps_growth_yoy", ("sec_xbrl.us-gaap.EarningsPerShareDiluted",)),
    ("revenue_growth_yoy", _REVENUE_FACT_KINDS),
)

# Momentum features computed from price bars. Listed here so the bundle
# always carries the keys (with None values when bars are missing).
_MOMENTUM_FEATURES: tuple[str, ...] = (
    "return_3m",
    "return_12m",
    "relative_strength",
)

# Window of historical facts to pull per YoY concept. Two annual filings
# is the minimum; 30 covers multi-year restatements + a comfortable
# margin for quarterly-only companies (filtered out post-fetch).
_YOY_FACT_WINDOW = 30

#: Symbol used as the benchmark in ``relative_strength`` (S&P 500 ETF).
#: The benchmark fact_kind ``historical_prices_window`` must be ingested
#: for this ticker separately (`iguanatrader research ingest openbb-prices SPY`).
BENCHMARK_SYMBOL = "SPY"

#: Calendar-day offsets used to anchor the return computations. The
#: lookup picks the bar with date <= (today - offset) closest to that
#: target, so weekends + holidays naturally fall back to the prior
#: trading day.
_RETURN_3M_OFFSET_DAYS = 90
_RETURN_12M_OFFSET_DAYS = 365


_HALF = Decimal("0.5")
_ZERO = Decimal("0")
_ONE = Decimal("1")


class TierAFeatureProvider:
    """Read native-PiT facts (EDGAR XBRL + FRED + OpenBB prices) into Tier-A values.

    Always returns ``(value, "A")`` or ``(None, "A")`` per feature.
    Backtest-safe: bitemporal ``recorded_from`` of every Tier-A fact
    matches the world-time it became known, so historical queries are
    deterministic.
    """

    TIER: str = "A"

    def __init__(self, repository: ResearchRepository) -> None:
        self._repo = repository

    async def fetch(
        self,
        symbol: str,
        since: datetime | None = None,
    ) -> FeatureBundle:
        """Return the bundle of Tier-A features for ``symbol``."""
        values: dict[str, FeatureValue] = {}
        citations: dict[str, UUID] = {}

        for feature_name, fact_kinds in _FACT_KIND_BY_FEATURE.items():
            fact = await self._latest_fact_for_kinds(symbol, fact_kinds, since=since)
            if fact is None:
                values[feature_name] = (None, "A")
                continue
            values[feature_name] = (fact.value_numeric, "A")
            if fact.id is not None:
                citations[feature_name] = fact.id

        # Derived YoY features — one repo call per concept (the fact_kinds
        # tuple may list a fallback chain when the canonical XBRL tag
        # has variants), then collapse restatements + compute
        # (latest - prior) / |prior|.
        for feature_name, source_kinds in _YOY_DERIVATIONS:
            yoy, anchor_fact = await self._compute_yoy(
                symbol=symbol, fact_kinds=source_kinds, since=since
            )
            values[feature_name] = (yoy, "A")
            if yoy is not None and anchor_fact is not None and anchor_fact.id is not None:
                citations[feature_name] = anchor_fact.id

        returns_bundle, anchor_price_fact = await self._compute_returns(symbol=symbol, since=since)
        values.update({name: (val, "A") for name, val in returns_bundle.items()})
        if anchor_price_fact is not None and anchor_price_fact.id is not None:
            for name in _MOMENTUM_FEATURES:
                if returns_bundle.get(name) is not None:
                    citations[name] = anchor_price_fact.id

        return FeatureBundle(values=values, fact_citations=citations)

    async def _latest_fact_for_kinds(
        self,
        symbol: str,
        fact_kinds: tuple[str, ...],
        *,
        since: datetime | None,
    ) -> ResearchFact | None:
        return await self._repo.latest_fact_by_kinds(
            symbol=symbol,
            fact_kinds=list(fact_kinds),
            since=since,
        )

    async def _compute_yoy(
        self,
        *,
        symbol: str,
        fact_kinds: tuple[str, ...],
        since: datetime | None,
    ) -> tuple[Decimal | None, ResearchFact | None]:
        """Compute YoY change of an XBRL concept, returning ``(yoy, anchor_fact)``.

        ``fact_kinds`` is a tuple of one or more candidate fact-kind
        identifiers — companies that switch XBRL revenue tags between
        fiscal years (e.g. ``Revenues`` → ``RevenueFromContract…``)
        appear in the union; the period-dedupe loop below picks the
        most-recently-recorded fact per ``effective_from``, so a tag
        switch is transparent to the consumer.
        """
        facts = await self._repo.facts_history_by_kinds(
            symbol=symbol,
            fact_kinds=list(fact_kinds),
            limit=_YOY_FACT_WINDOW,
            require_recorded_before=since,
        )
        annual = [f for f in facts if _is_annual_filing(f)]
        if len(annual) < 2:
            return (None, None)

        latest_per_period: list[ResearchFact] = []
        seen_periods: set[datetime] = set()
        for f in annual:
            if f.effective_from in seen_periods:
                continue
            seen_periods.add(f.effective_from)
            latest_per_period.append(f)
            if len(latest_per_period) >= 2:
                break

        if len(latest_per_period) < 2:
            return (None, None)

        latest, prior = latest_per_period[0], latest_per_period[1]
        if latest.value_numeric is None or prior.value_numeric is None:
            return (None, latest)
        if prior.value_numeric == 0:
            return (None, latest)
        try:
            yoy = (latest.value_numeric - prior.value_numeric) / abs(prior.value_numeric)
        except (DivisionByZero, InvalidOperation):
            return (None, latest)
        return (yoy, latest)

    async def _compute_returns(
        self,
        *,
        symbol: str,
        since: datetime | None,
    ) -> tuple[dict[str, Decimal | None], ResearchFact | None]:
        """Compute ``return_3m``, ``return_12m``, ``relative_strength`` from price bars.

        Returns ``(values_by_name, anchor_fact)``. ``anchor_fact`` is the
        symbol's historical_prices_window fact id (citation anchor for
        all three derived returns). Missing benchmark data degrades
        gracefully — relative_strength becomes None while the absolute
        returns still populate.
        """
        empty: dict[str, Decimal | None] = dict.fromkeys(_MOMENTUM_FEATURES)
        reference = since or utc_now()

        sym_fact = await self._repo.latest_fact_by_kinds(
            symbol=symbol,
            fact_kinds=["historical_prices_window"],
            since=None,
            require_recorded_before=reference,
        )
        if sym_fact is None or not isinstance(sym_fact.value_jsonb, dict):
            return (empty, None)
        sym_bars = sym_fact.value_jsonb.get("bars") or []
        if not isinstance(sym_bars, list):
            return (empty, sym_fact)

        ref_date = reference.date()
        target_now = ref_date
        target_3mo = ref_date - timedelta(days=_RETURN_3M_OFFSET_DAYS)
        target_12mo = ref_date - timedelta(days=_RETURN_12M_OFFSET_DAYS)

        sym_now = _close_on_or_before(sym_bars, target_now)
        sym_3mo = _close_on_or_before(sym_bars, target_3mo)
        sym_12mo = _close_on_or_before(sym_bars, target_12mo)

        ret_3m = _safe_return(sym_now, sym_3mo)
        ret_12m = _safe_return(sym_now, sym_12mo)

        rel_str: Decimal | None = None
        if ret_12m is not None:
            spy_fact = await self._repo.latest_fact_by_kinds(
                symbol=BENCHMARK_SYMBOL,
                fact_kinds=["historical_prices_window"],
                since=None,
                require_recorded_before=reference,
            )
            if spy_fact is not None and isinstance(spy_fact.value_jsonb, dict):
                spy_bars = spy_fact.value_jsonb.get("bars") or []
                if isinstance(spy_bars, list):
                    spy_now = _close_on_or_before(spy_bars, target_now)
                    spy_12mo = _close_on_or_before(spy_bars, target_12mo)
                    spy_ret_12m = _safe_return(spy_now, spy_12mo)
                    if spy_ret_12m is not None:
                        rel_str = _clip(_HALF + (ret_12m - spy_ret_12m) / Decimal("2"))

        return (
            {"return_3m": ret_3m, "return_12m": ret_12m, "relative_strength": rel_str},
            sym_fact,
        )


def _is_annual_filing(fact: ResearchFact) -> bool:
    """Return True when the XBRL fact_metadata flags ``fiscal_period == 'FY'``."""
    meta = fact.fact_metadata or {}
    return meta.get("fiscal_period") == "FY"


def _close_on_or_before(bars: list[Any], target: Any) -> Decimal | None:
    """Return the close price of the bar with ``date`` closest to ``target`` from below.

    ``target`` is a :class:`datetime.date`; bar dates may be ISO strings
    or date objects depending on whether the payload made the JSON
    round-trip. ISO 8601 ``YYYY-MM-DD`` strings lex-sort correctly so
    string-vs-string comparison is safe.
    """
    target_str = target.isoformat()
    best: dict[str, Any] | None = None
    best_key: str = ""
    for bar in bars:
        if not isinstance(bar, dict):
            continue
        raw_date = bar.get("date")
        if not raw_date:
            continue
        key = raw_date if isinstance(raw_date, str) else str(raw_date)
        key = key[:10]  # accept "2024-01-15T00:00:00+00:00" too
        if key > target_str:
            continue
        if key > best_key:
            best = bar
            best_key = key
    if best is None:
        return None
    close = best.get("adj_close") or best.get("close")
    if close is None:
        return None
    try:
        return Decimal(str(close))
    except InvalidOperation:
        return None


def _safe_return(now: Decimal | None, past: Decimal | None) -> Decimal | None:
    """Return ``(now - past) / past`` or None if inputs are missing / past is 0."""
    if now is None or past is None or past == 0:
        return None
    try:
        return (now - past) / past
    except (DivisionByZero, InvalidOperation):
        return None


def _clip(value: Decimal) -> Decimal:
    """Clip ``value`` to ``[0, 1]``."""
    if value < _ZERO:
        return _ZERO
    if value > _ONE:
        return _ONE
    return value


__all__ = ["BENCHMARK_SYMBOL", "TierAFeatureProvider"]
