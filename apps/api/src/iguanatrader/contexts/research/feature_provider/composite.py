"""Composite feature provider — dispatches per methodology recipe.

Per slice R5 design D2: each methodology has a ``required_features``
recipe (which features it consumes); the composite consults the
matching tier provider per feature.

R5's MVP recipe registry is hardcoded here; v1.5 may extract to YAML.
"""

from __future__ import annotations

from datetime import datetime

from iguanatrader.contexts.research.feature_provider.base import (
    FeatureBundle,
    Tier,
    merge_bundles,
)
from iguanatrader.contexts.research.feature_provider.tier_a import TierAFeatureProvider
from iguanatrader.contexts.research.feature_provider.tier_b import TierBFeatureProvider
from iguanatrader.contexts.research.feature_provider.tier_c import TierCFeatureProvider

# Per-methodology recipe: feature_name → preferred tier. Composite
# fetches the corresponding tier provider's value for each feature.
_RECIPE_BY_METHODOLOGY: dict[str, dict[str, Tier]] = {
    "three_pillar": {
        "eps_growth_yoy": "A",
        "revenue_growth_yoy": "A",
        "forward_pe": "B",
        "pb_ratio": "B",
        "return_3m": "A",
        "return_12m": "A",
        "relative_strength": "A",
    },
    "canslim": {
        "current_eps_growth_yoy": "A",
        "annual_eps_growth_3y": "A",
        "price_at_or_near_52w_high": "A",
        "volume_surge_ratio": "A",
        "sector_relative_strength": "A",
        "institutional_holding_change_pct": "B",
        "spy_above_50dma": "A",
    },
    "magic_formula": {
        "ebit_to_ev": "B",
        "return_on_capital": "B",
    },
    "qarp": {
        "return_on_equity": "B",
        "return_on_invested_capital": "B",
        "debt_to_equity": "B",
        "forward_pe": "B",
        "ev_to_ebitda": "B",
        "eps_growth_yoy": "A",
    },
    "multi_factor": {
        "market_beta": "A",
        "market_cap_smb_score": "A",
        "book_to_market": "B",
        "operating_margin": "B",
        "capex_to_assets": "B",
        "return_12m_minus_1": "A",
    },
}


class CompositeFeatureProvider:
    """Aggregates Tier-A/B/C providers per methodology recipe."""

    def __init__(
        self,
        tier_a: TierAFeatureProvider,
        tier_b: TierBFeatureProvider,
        tier_c: TierCFeatureProvider,
    ) -> None:
        self._a = tier_a
        self._b = tier_b
        self._c = tier_c

    async def fetch(
        self,
        symbol: str,
        methodology: str,
        since: datetime | None = None,
    ) -> FeatureBundle:
        """Fetch the bundle dictated by ``methodology``'s recipe.

        Tier-B providers receive ``since`` so the backtest-safety
        constraint (recorded_from <= since) holds. Tier-C providers
        receive ``since`` but the MVP recipe registry has no Tier-C
        entries.
        """
        if methodology not in _RECIPE_BY_METHODOLOGY:
            raise ValueError(
                f"unknown methodology {methodology!r}; "
                f"expected one of {sorted(_RECIPE_BY_METHODOLOGY)}"
            )

        a_bundle = await self._a.fetch(symbol=symbol, since=since)
        b_bundle = await self._b.fetch(symbol=symbol, since=since)
        c_bundle = await self._c.fetch(symbol=symbol, since=since)

        merged = merge_bundles(a_bundle, b_bundle, c_bundle)
        # Filter to just the recipe's features.
        recipe = _RECIPE_BY_METHODOLOGY[methodology]
        filtered_values = {name: merged.values[name] for name in recipe if name in merged.values}
        # For features in the recipe that no provider returned, fill with
        # (None, recipe_tier).
        for name, tier in recipe.items():
            if name not in filtered_values:
                filtered_values[name] = (None, tier)
        filtered_citations = {
            name: merged.fact_citations[name] for name in recipe if name in merged.fact_citations
        }
        return FeatureBundle(values=filtered_values, fact_citations=filtered_citations)


__all__ = ["CompositeFeatureProvider"]
