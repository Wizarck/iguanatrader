"""Feature provider Protocol + value types (slice R5 design D2).

* :class:`Tier` — ``Literal["A", "B", "C"]``.
* :class:`FeatureValue` — ``tuple[Decimal | None, Tier]``.
* :class:`FeatureBundle` — ``dict[str, FeatureValue]`` plus
  ``fact_citations: dict[str, UUID]`` sidecar (feature name → fact id
  used by the citation resolver).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol
from uuid import UUID

Tier = Literal["A", "B", "C"]
FeatureValue = tuple[Decimal | None, Tier]


@dataclass(frozen=True, slots=True)
class FeatureBundle:
    """Aggregate of values + per-feature citations.

    ``values`` keys are feature names (``forward_pe``, ``eps_growth_yoy``);
    each value is ``(Decimal | None, Tier)``. ``fact_citations`` maps
    feature names to the originating ``research_facts.id`` so the
    citation resolver can render the audit chain. Feature names without
    a citation entry are still allowed (computed features that don't
    map to a single fact — the synthesizer's audit_trail_entry captures
    the formula instead).
    """

    values: dict[str, FeatureValue]
    fact_citations: dict[str, UUID] = field(default_factory=dict)

    def values_only(self) -> dict[str, Decimal | None]:
        """Return ``{name: decimal_or_none}`` — what methodology score()s consume."""
        return {name: value for name, (value, _tier) in self.values.items()}

    def tiers_only(self) -> dict[str, Tier]:
        """Return ``{name: tier}``."""
        return {name: tier for name, (_v, tier) in self.values.items()}


class FeatureProvider(Protocol):
    """Sync provider Protocol consumed by :class:`CompositeFeatureProvider`."""

    def fetch(
        self,
        symbol: str,
        since: datetime | None,
    ) -> FeatureBundle:
        """Return a partial :class:`FeatureBundle` for ``symbol``."""
        ...


def merge_bundles(*bundles: FeatureBundle) -> FeatureBundle:
    """Concatenate multiple bundles into one. Later bundles override earlier ones."""
    merged_values: dict[str, FeatureValue] = {}
    merged_citations: dict[str, UUID] = {}
    for b in bundles:
        merged_values.update(b.values)
        merged_citations.update(b.fact_citations)
    return FeatureBundle(values=merged_values, fact_citations=merged_citations)


__all__ = [
    "FeatureBundle",
    "FeatureProvider",
    "FeatureValue",
    "Tier",
    "merge_bundles",
]
