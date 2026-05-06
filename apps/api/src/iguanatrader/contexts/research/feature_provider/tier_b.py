"""Tier-B feature provider — snapshot-collected sources (slice R5 D2).

⚠️ **TIER-B: forbidden in backtest contexts.** Use only for live +
scheduled refresh. The CI assertion at
``apps/api/tests/unit/contexts/research/test_feature_provider_tier.py``
walks ``contexts/trading/strategies/`` and FAILS if any code path
calls :meth:`TierBFeatureProvider.fetch` without an explicit
``since: datetime`` argument.

Tier-B feature names map to fact_kinds from Wave-3 R3/R4 sources:

* ``analyst_rating_avg`` ← ``openbb-sidecar.analyst_ratings``.
* ``esg_score`` ← ``openbb-sidecar.esg_score``.
* ``fundamentals_snapshot`` ← ``openbb-sidecar.fundamentals``.

Returns ``(value, "B")`` only if ``recorded_from <= since``; else
``(None, "B")``. None-leakage means the methodology emits "missing
feature" rather than silently using future-knowledge.
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
    from iguanatrader.contexts.research.repository import ResearchRepository


_FACT_KIND_BY_FEATURE: dict[str, tuple[str, ...]] = {
    "analyst_rating_avg": ("openbb-sidecar.analyst_ratings", "openbb_analyst_ratings"),
    "esg_score": ("openbb-sidecar.esg_score", "openbb_esg_score"),
    "fundamentals_snapshot": ("openbb-sidecar.fundamentals", "openbb_fundamentals"),
}


class TierBFeatureProvider:
    """Snapshot-collected feature provider with strict ``since`` constraint."""

    TIER: str = "B"

    def __init__(self, repository: ResearchRepository) -> None:
        self._repo = repository

    async def fetch(
        self,
        symbol: str,
        since: datetime | None = None,
    ) -> FeatureBundle:
        """Return Tier-B features. ``since=None`` returns all-None bundle.

        The all-None on ``since=None`` behaviour is intentional: callers
        in backtest contexts MUST pass an explicit ``since`` to use this
        provider. Live callers pass ``since=datetime.utcnow()``.
        """
        values: dict[str, FeatureValue] = {}
        citations: dict[str, UUID] = {}

        if since is None:
            for feature_name in _FACT_KIND_BY_FEATURE:
                values[feature_name] = (None, "B")
            return FeatureBundle(values=values, fact_citations=citations)

        for feature_name, fact_kinds in _FACT_KIND_BY_FEATURE.items():
            fact = await self._repo.latest_fact_by_kinds(
                symbol=symbol,
                fact_kinds=list(fact_kinds),
                since=since,
                require_recorded_before=since,
            )
            if fact is None or fact.value_numeric is None:
                values[feature_name] = (None, "B")
                continue
            values[feature_name] = (fact.value_numeric, "B")
            if fact.id is not None:
                citations[feature_name] = fact.id

        return FeatureBundle(values=values, fact_citations=citations)


__all__ = ["TierBFeatureProvider"]
