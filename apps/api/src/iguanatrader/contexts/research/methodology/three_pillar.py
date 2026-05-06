"""3-pillar methodology — growth + value + momentum (slice R5 design D1).

Canonical recipe (no single citation; this is a popular discretionary
synthesis used by long-horizon equity desks):

* Growth pillar (weight 1/3): ``eps_growth_yoy``, ``revenue_growth_yoy``.
* Value pillar (weight 1/3): ``forward_pe`` (lower → higher score),
  ``pb_ratio`` (lower → higher score; reasonable bound 5).
* Momentum pillar (weight 1/3): ``return_3m``, ``return_12m``,
  ``relative_strength`` (vs SPY).

The pure-function returns deterministic ranking + score + rationale
for the same feature input. The LLM later expands the rationale into
a brief body; methodology fidelity is owned here.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from iguanatrader.contexts.research.methodology.base import (
    ZERO,
    MethodologyResult,
    PillarScore,
    clip_unit_interval,
    normalise_growth,
    normalise_inverse_pe,
)

_GROWTH_FEATURES = ("eps_growth_yoy", "revenue_growth_yoy")
_VALUE_FEATURES = ("forward_pe", "pb_ratio")
_MOMENTUM_FEATURES = ("return_3m", "return_12m", "relative_strength")
_PILLAR_WEIGHT = Decimal("1") / Decimal("3")


def score(features: Mapping[str, Decimal | None]) -> MethodologyResult:
    """Compute the 3-pillar score for ``features``.

    Required feature keys: ``eps_growth_yoy``, ``revenue_growth_yoy``,
    ``forward_pe``, ``pb_ratio``, ``return_3m``, ``return_12m``,
    ``relative_strength``. Missing keys → ``None`` per pillar →
    ``missing_features`` populated.
    """
    missing: list[str] = []

    growth_values = [
        normalise_growth(features.get(k), target=Decimal("0.25")) for k in _GROWTH_FEATURES
    ]
    growth_score = (
        (sum(growth_values, ZERO) / Decimal(len(_GROWTH_FEATURES))) if growth_values else ZERO
    )
    for k in _GROWTH_FEATURES:
        if features.get(k) is None:
            missing.append(k)

    value_subscores = [
        normalise_inverse_pe(features.get("forward_pe"), max_pe=Decimal("30")),
        normalise_inverse_pe(features.get("pb_ratio"), max_pe=Decimal("5")),
    ]
    value_score = sum(value_subscores, ZERO) / Decimal(len(_VALUE_FEATURES))
    for k in _VALUE_FEATURES:
        if features.get(k) is None:
            missing.append(k)

    momentum_subscores = [
        normalise_growth(features.get("return_3m"), target=Decimal("0.10")),
        normalise_growth(features.get("return_12m"), target=Decimal("0.30")),
        clip_unit_interval(features.get("relative_strength") or ZERO),
    ]
    momentum_score = sum(momentum_subscores, ZERO) / Decimal(len(_MOMENTUM_FEATURES))
    for k in _MOMENTUM_FEATURES:
        if features.get(k) is None:
            missing.append(k)

    pillars = {
        "growth": PillarScore(
            name="growth", score=clip_unit_interval(growth_score), weight=_PILLAR_WEIGHT
        ),
        "value": PillarScore(
            name="value", score=clip_unit_interval(value_score), weight=_PILLAR_WEIGHT
        ),
        "momentum": PillarScore(
            name="momentum", score=clip_unit_interval(momentum_score), weight=_PILLAR_WEIGHT
        ),
    }
    overall = sum((p.score * p.weight for p in pillars.values()), ZERO)
    overall = clip_unit_interval(overall)

    rationale = (
        f"3-pillar composite: growth={pillars['growth'].score:.3f}, "
        f"value={pillars['value'].score:.3f}, momentum={pillars['momentum'].score:.3f}. "
        f"Overall {overall:.3f} on a 0-1 scale (1.0 = strongest signal). "
    )
    if missing:
        rationale += f"Missing feature inputs: {', '.join(sorted(set(missing)))}."

    return MethodologyResult(
        overall_score=overall,
        ranking=1,
        pillars=pillars,
        rationale=rationale,
        missing_features=sorted(set(missing)),
    )


__all__ = ["score"]
