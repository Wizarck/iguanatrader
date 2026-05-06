"""Shared methodology dataclasses (slice R5 design D1).

Pure-functional methodology framework:

* :class:`PillarScore` — one entry inside :class:`MethodologyResult.pillars`.
  Names + weights + contributing fact ids per pillar (e.g. CANSLIM's
  ``"C"`` pillar has weight 0.143 and aggregates ``current_eps_growth_yoy``).
* :class:`MethodologyResult` — what every ``score(features)`` returns.

All scores are :class:`Decimal` in ``[0, 1]`` (never ``float``).
``ranking`` is 1-based; methodologies that don't produce a ranking
(absolute score frameworks) emit ``ranking=1`` and document in their
docstring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass(frozen=True, slots=True)
class PillarScore:
    """One pillar inside a :class:`MethodologyResult`.

    ``score`` is the pillar's normalised value in ``[0, 1]``. ``weight``
    is the pillar's contribution to the methodology's overall_score
    (sum of weights across all pillars equals 1.0). ``contributing_facts``
    lists the fact ids that fed the pillar — used by the citation
    resolver to highlight per-pillar provenance in the audit trail.
    """

    name: str
    score: Decimal
    weight: Decimal
    contributing_facts: list[UUID] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class MethodologyResult:
    """Outcome of a methodology's pure ``score(features)`` function.

    ``overall_score`` is in ``[0, 1]`` — the weighted aggregate across
    pillars. ``ranking`` is 1-based; the synthesizer renders the symbol's
    rank within a peer group when methodology produces one (e.g. Magic
    Formula's combined-rank). ``rationale`` is a short prose seed that
    the LLM expands into the brief body. ``missing_features`` lists
    the feature names that were ``None`` in the input — the synthesizer
    sets ``partial=true`` on the brief if any tier-A required feature
    is missing.
    """

    overall_score: Decimal
    ranking: int
    pillars: dict[str, PillarScore]
    rationale: str
    missing_features: list[str] = field(default_factory=list)


def clip_unit_interval(value: Decimal) -> Decimal:
    """Return ``value`` clipped to ``[0, 1]``."""
    if value < ZERO:
        return ZERO
    if value > ONE:
        return ONE
    return value


def normalise_growth(value: Decimal | None, *, target: Decimal) -> Decimal:
    """Map a growth-rate (e.g. 0.25 for 25% YoY) to ``[0, 1]`` with
    ``target`` as the saturation point.

    ``None`` → ``Decimal("0")`` (caller appends to missing_features).
    Negative values clip to ``0``; values >= target clip to ``1``.
    """
    if value is None or target <= ZERO:
        return ZERO
    return clip_unit_interval(value / target)


def normalise_inverse_pe(value: Decimal | None, *, max_pe: Decimal) -> Decimal:
    """Map a P/E ratio to ``[0, 1]`` (lower P/E → higher score).

    ``None`` → ``ZERO`` (no signal). ``value <= 0`` → ``ZERO`` (negative
    earnings or trailing P/E with zero earnings is not "cheap").
    ``value >= max_pe`` → ``ZERO`` (overvalued). Otherwise: linear
    inverse from max_pe down to 0.
    """
    if value is None or value <= ZERO or value >= max_pe:
        return ZERO
    return clip_unit_interval(ONE - (value / max_pe))


__all__ = [
    "ONE",
    "ZERO",
    "MethodologyResult",
    "PillarScore",
    "clip_unit_interval",
    "normalise_growth",
    "normalise_inverse_pe",
]
