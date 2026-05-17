"""Tier-B feature provider — snapshot-collected sources (slice R5 D2, R3 extraction rewrite).

⚠️ **TIER-B: forbidden in backtest contexts.** Use only for live +
scheduled refresh. The CI assertion at
``apps/api/tests/unit/contexts/research/test_feature_provider_tier.py``
walks ``contexts/trading/strategies/`` and FAILS if any code path
calls :meth:`TierBFeatureProvider.fetch` without an explicit
``since: datetime`` argument.

Tier-B reads OpenBB sidecar snapshot facts and extracts scalar features
from each fact's ``value_jsonb`` payload. The fact_kind is whatever the
adapter writes (``fundamentals``, ``analyst_ratings``, ``esg_score`` —
no source prefix; the source itself is identified by ``source_id``).

The extraction map below pairs each feature name with the fact_kind
that carries it and the JSON key on the payload. One adapter fetch
produces one fact per endpoint; tier_b fans those out into N scalar
features without re-querying.

Returns ``(value, "B")`` only if ``recorded_from <= since``; else
``(None, "B")``. None-leakage means the methodology emits "missing
feature" rather than silently using future-knowledge.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any
from uuid import UUID

from iguanatrader.contexts.research.feature_provider.base import (
    FeatureBundle,
    FeatureValue,
)

if TYPE_CHECKING:
    from iguanatrader.contexts.research.models import ResearchFact
    from iguanatrader.contexts.research.repository import ResearchRepository


# (feature_name, fact_kind, payload_key) — one row per scalar feature.
# Multiple features may share the same fact_kind (one HTTP call to the
# sidecar → many features), so we group by fact_kind at fetch time.
_FEATURE_EXTRACTORS: tuple[tuple[str, str, str], ...] = (
    ("forward_pe", "fundamentals", "forward_pe"),
    ("pb_ratio", "fundamentals", "price_to_book"),
    ("pe_ratio", "fundamentals", "pe_ratio"),
    ("market_cap", "fundamentals", "market_cap"),
    ("dividend_yield", "fundamentals", "dividend_yield"),
    ("analyst_target_price", "analyst_ratings", "target_price"),
    ("analyst_count", "analyst_ratings", "analyst_count"),
    ("esg_score", "esg_score", "esg_score"),
    ("environmental_score", "esg_score", "environmental_score"),
    ("social_score", "esg_score", "social_score"),
    ("governance_score", "esg_score", "governance_score"),
)


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
        feature_names = [feat for feat, _kind, _key in _FEATURE_EXTRACTORS]

        values: dict[str, FeatureValue] = {}
        citations: dict[str, UUID] = {}

        if since is None:
            for feature_name in feature_names:
                values[feature_name] = (None, "B")
            return FeatureBundle(values=values, fact_citations=citations)

        # One fact per distinct fact_kind, reused across all features that
        # extract from that payload.
        fact_kinds = {kind for _feat, kind, _key in _FEATURE_EXTRACTORS}
        fact_by_kind: dict[str, ResearchFact | None] = {}
        for kind in fact_kinds:
            fact_by_kind[kind] = await self._repo.latest_fact_by_kinds(
                symbol=symbol,
                fact_kinds=[kind],
                since=None,  # extracts the latest snapshot, not constrained by effective_from
                require_recorded_before=since,
            )

        for feature_name, fact_kind, payload_key in _FEATURE_EXTRACTORS:
            fact = fact_by_kind.get(fact_kind)
            if fact is None:
                values[feature_name] = (None, "B")
                continue
            scalar = _extract_scalar(fact.value_jsonb, payload_key)
            if scalar is None:
                values[feature_name] = (None, "B")
                continue
            values[feature_name] = (scalar, "B")
            if fact.id is not None:
                citations[feature_name] = fact.id

        return FeatureBundle(values=values, fact_citations=citations)


def _extract_scalar(payload: Any, key: str) -> Decimal | None:
    """Coerce ``payload[key]`` to :class:`Decimal`. None on absent / non-numeric.

    Handles the three shapes the sidecar emits: a flat dict (fundamentals,
    ratings, esg), a value the JSON column already parsed for us, or a
    string we still need to parse. Lists and nested objects fall through
    to None — caller must add an explicit JSON path if a future endpoint
    nests scalars.
    """
    if not isinstance(payload, dict):
        return None
    raw = payload.get(key)
    if raw is None:
        return None
    if isinstance(raw, bool):
        # bool is a subclass of int in Python — guard against silent coercion.
        return None
    if isinstance(raw, int | float | Decimal):
        try:
            return Decimal(str(raw))
        except InvalidOperation:
            return None
    if isinstance(raw, str):
        try:
            return Decimal(raw)
        except InvalidOperation:
            return None
    return None


def tier_b_feature_names() -> Iterable[str]:
    """Expose the feature surface for tests + recipe sanity checks."""
    return (feat for feat, _kind, _key in _FEATURE_EXTRACTORS)


__all__ = ["TierBFeatureProvider", "tier_b_feature_names"]
