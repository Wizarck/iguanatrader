"""Tier-A feature provider — native point-in-time sources (slice R5 D2).

Tier-A feature names map to fact_kinds R2 ingested:

* ``eps_diluted`` ← ``sec_xbrl.us-gaap.EarningsPerShareDiluted``
* ``revenue`` ← ``sec_xbrl.us-gaap.Revenues``
* ``forward_pe`` — computed downstream (price / forward EPS); not native.
* ``cpi_yoy`` ← ``fred.CPIAUCSL`` (year-over-year).
* ``unemployment_rate`` ← ``fred.UNRATE``.
* ``fed_funds_rate`` ← ``fred.DFF``.

This MVP implementation reads the latest fact for each known mapping.
Computed-feature derivation (P/E, growth-rate-YoY, etc.) is the
:class:`CompositeFeatureProvider`'s job; tier_a only surfaces raw
native facts.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from iguanatrader.contexts.research.feature_provider.base import (
    FeatureBundle,
    FeatureValue,
)

if TYPE_CHECKING:
    from iguanatrader.contexts.research.models import ResearchFact
    from iguanatrader.contexts.research.repository import ResearchRepository


# Mapping from feature_name → list of acceptable fact_kind patterns.
# Order matters: first match wins.
_FACT_KIND_BY_FEATURE: dict[str, tuple[str, ...]] = {
    "eps_diluted": ("sec_xbrl.us-gaap.EarningsPerShareDiluted",),
    "revenue": ("sec_xbrl.us-gaap.Revenues",),
    "cpi_yoy": ("fred.CPIAUCSL",),
    "unemployment_rate": ("fred.UNRATE",),
    "fed_funds_rate": ("fred.DFF",),
}


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


__all__ = ["TierAFeatureProvider"]
