"""Tier-C feature provider — bootstrap-only sources (slice R5 D2).

Tier-C facts are one-shot bootstrap loads (WGI governance,
V-Dem democracy, ESG sustainability one-shots). Available only at the
bootstrapped timestamp; outside that window the value is ``None``.

In MVP-R5 the registry is empty — Tier-C fact ingestion is wired up
in Wave-4 (post-MVP). This module exists to honour the
:class:`FeatureProvider` Protocol (so :class:`CompositeFeatureProvider`
has a stable shape) and so the test surface can exercise the all-None
path.
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
    # Future R6: ``wgi_governance`` ← ``wgi.governance``
    # Future R6: ``vdem_democracy`` ← ``vdem.democracy_index``
}


class TierCFeatureProvider:
    """Bootstrap-only feature provider; emits all-None until R6 wires fact_kinds."""

    TIER: str = "C"

    def __init__(self, repository: ResearchRepository) -> None:
        self._repo = repository

    async def fetch(
        self,
        symbol: str,
        since: datetime | None = None,
    ) -> FeatureBundle:
        values: dict[str, FeatureValue] = dict.fromkeys(_FACT_KIND_BY_FEATURE, (None, "C"))
        citations: dict[str, UUID] = {}
        return FeatureBundle(values=values, fact_citations=citations)


__all__ = ["TierCFeatureProvider"]
