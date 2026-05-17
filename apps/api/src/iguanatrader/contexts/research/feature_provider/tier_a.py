"""Tier-A feature provider — native point-in-time sources (slice R5 D2, R3 YoY).

Tier-A feature names map to fact_kinds R2 ingested:

* ``eps_diluted`` ← ``sec_xbrl.us-gaap.EarningsPerShareDiluted``
* ``revenue`` ← ``sec_xbrl.us-gaap.Revenues``
* ``cpi_yoy`` ← ``fred.CPIAUCSL`` (year-over-year).
* ``unemployment_rate`` ← ``fred.UNRATE``.
* ``fed_funds_rate`` ← ``fred.DFF``.

Slice R3 adds derived features computed from a window of XBRL facts:

* ``eps_growth_yoy`` — (latest_FY EPS - prior_FY EPS) / |prior_FY EPS|.
* ``revenue_growth_yoy`` — (latest_FY Revenue - prior_FY Revenue) / |prior_FY Revenue|.

The YoY computation pulls the most recent two annual filings (``fp=FY``)
from ``fact_metadata`` and divides. Restatements of the same fiscal
year (10-K/A) are collapsed by taking the latest ``recorded_from`` per
``effective_from`` date.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, DivisionByZero, InvalidOperation
from typing import TYPE_CHECKING
from uuid import UUID

from iguanatrader.contexts.research.feature_provider.base import (
    FeatureBundle,
    FeatureValue,
)

if TYPE_CHECKING:
    from iguanatrader.contexts.research.models import ResearchFact
    from iguanatrader.contexts.research.repository import ResearchRepository


# Native-fact mappings — one fact_kind, one feature.
_FACT_KIND_BY_FEATURE: dict[str, tuple[str, ...]] = {
    "eps_diluted": ("sec_xbrl.us-gaap.EarningsPerShareDiluted",),
    "revenue": ("sec_xbrl.us-gaap.Revenues",),
    "cpi_yoy": ("fred.CPIAUCSL",),
    "unemployment_rate": ("fred.UNRATE",),
    "fed_funds_rate": ("fred.DFF",),
}

# Derived YoY features — (feature_name, source_fact_kind).
_YOY_DERIVATIONS: tuple[tuple[str, str], ...] = (
    ("eps_growth_yoy", "sec_xbrl.us-gaap.EarningsPerShareDiluted"),
    ("revenue_growth_yoy", "sec_xbrl.us-gaap.Revenues"),
)

# Window of historical facts to pull per YoY concept. Two annual filings
# is the minimum; 30 covers multi-year restatements + a comfortable
# margin for quarterly-only companies (filtered out post-fetch).
_YOY_FACT_WINDOW = 30


class TierAFeatureProvider:
    """Read native-PiT facts (EDGAR XBRL + FRED) into Tier-A feature values.

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

        # Derived YoY features — one repo call per concept, then collapse
        # restatements + compute (latest - prior) / |prior|.
        for feature_name, source_kind in _YOY_DERIVATIONS:
            yoy, anchor_fact = await self._compute_yoy(
                symbol=symbol, fact_kind=source_kind, since=since
            )
            values[feature_name] = (yoy, "A")
            if yoy is not None and anchor_fact is not None and anchor_fact.id is not None:
                citations[feature_name] = anchor_fact.id

        return FeatureBundle(values=values, fact_citations=citations)

    async def _latest_fact_for_kinds(
        self,
        symbol: str,
        fact_kinds: tuple[str, ...],
        *,
        since: datetime | None,
    ) -> ResearchFact | None:
        """Return the most recent fact matching any of ``fact_kinds`` for ``symbol``."""
        return await self._repo.latest_fact_by_kinds(
            symbol=symbol,
            fact_kinds=list(fact_kinds),
            since=since,
        )

    async def _compute_yoy(
        self,
        *,
        symbol: str,
        fact_kind: str,
        since: datetime | None,
    ) -> tuple[Decimal | None, ResearchFact | None]:
        """Compute YoY change of an XBRL concept, returning ``(yoy, anchor_fact)``.

        ``anchor_fact`` is the latest-period fact used as numerator; its
        id is the citation anchor for the derived feature.

        Algorithm: pull a window of FY-only XBRL facts (``fp=FY``),
        collapse restatements by keeping the latest-recorded per
        ``effective_from`` date, then divide the two most recent values.
        Returns ``(None, None)`` whenever fewer than two distinct FY
        periods are available or the prior value is zero.
        """
        facts = await self._repo.facts_history_by_kinds(
            symbol=symbol,
            fact_kinds=[fact_kind],
            limit=_YOY_FACT_WINDOW,
            require_recorded_before=since,
        )
        annual = [f for f in facts if _is_annual_filing(f)]
        if len(annual) < 2:
            return (None, None)

        # Collapse restatements: facts arrive sorted by effective_from DESC
        # then recorded_from DESC; first occurrence of each effective_from
        # wins (newest revision of that fiscal year).
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


def _is_annual_filing(fact: ResearchFact) -> bool:
    """Return True when the XBRL fact_metadata flags ``fiscal_period == 'FY'``."""
    meta = fact.fact_metadata or {}
    return meta.get("fiscal_period") == "FY"


__all__ = ["TierAFeatureProvider"]
