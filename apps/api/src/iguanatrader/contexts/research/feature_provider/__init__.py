"""Tier-aware feature provider — slice R5 design D2.

Three concrete providers (Tier-A native PiT, Tier-B snapshot, Tier-C
bootstrap) are composed by :class:`CompositeFeatureProvider`. Returns
typed :class:`FeatureBundle` mapping feature name → (value, tier).

Per AGENTS.md §11: Tier-B usage in backtest features is forbidden via
the CI assertion at
``apps/api/tests/unit/contexts/research/test_feature_provider_tier.py``.
"""

from __future__ import annotations

from iguanatrader.contexts.research.feature_provider.base import (
    FeatureBundle,
    FeatureProvider,
    FeatureValue,
    Tier,
    merge_bundles,
)
from iguanatrader.contexts.research.feature_provider.composite import (
    CompositeFeatureProvider,
)
from iguanatrader.contexts.research.feature_provider.tier_a import TierAFeatureProvider
from iguanatrader.contexts.research.feature_provider.tier_b import TierBFeatureProvider
from iguanatrader.contexts.research.feature_provider.tier_c import TierCFeatureProvider

__all__ = [
    "CompositeFeatureProvider",
    "FeatureBundle",
    "FeatureProvider",
    "FeatureValue",
    "Tier",
    "TierAFeatureProvider",
    "TierBFeatureProvider",
    "TierCFeatureProvider",
    "merge_bundles",
]
