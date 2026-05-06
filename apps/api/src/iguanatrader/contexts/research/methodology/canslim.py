"""CANSLIM methodology (William O'Neil, 'How to Make Money in Stocks', 2002 ed.).

7 criteria, equal-weighted (~14.3% each):

* **C** — Current quarterly EPS growth ≥ 25% YoY (``current_eps_growth_yoy``).
* **A** — Annual EPS growth ≥ 25% over 3 years (``annual_eps_growth_3y``).
* **N** — New high / new product / new management. MVP proxy:
  ``price_at_or_near_52w_high`` (1.0 if within 5% of 52w high; linear
  interpolation otherwise).
* **S** — Supply (low float) + demand. MVP proxy: ``volume_surge_ratio``
  (recent 50-day volume / prior 200-day baseline) — values >= 1.5
  → 1.0 (institutional accumulation).
* **L** — Leader (sector relative strength ≥ 80 percentile). MVP feature:
  ``sector_relative_strength`` (0-100 scale, normalised to [0,1]).
* **I** — Institutional sponsorship trend (``institutional_holding_change_pct``).
  Positive → 1.0; flat → 0.5; negative → 0.0.
* **M** — Market direction. MVP proxy: ``spy_above_50dma`` (boolean
  encoded as Decimal 0 or 1).

Citation: O'Neil, W. (2002). 'How to Make Money in Stocks: A Winning
System in Good Times and Bad' (3rd ed.). McGraw-Hill.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from iguanatrader.contexts.research.methodology.base import (
    ONE,
    ZERO,
    MethodologyResult,
    PillarScore,
    clip_unit_interval,
    normalise_growth,
)

_CRITERIA = ("C", "A", "N", "S", "L", "I", "M")
_FEATURE_BY_CRITERION = {
    "C": "current_eps_growth_yoy",
    "A": "annual_eps_growth_3y",
    "N": "price_at_or_near_52w_high",
    "S": "volume_surge_ratio",
    "L": "sector_relative_strength",
    "I": "institutional_holding_change_pct",
    "M": "spy_above_50dma",
}
_WEIGHT = ONE / Decimal(len(_CRITERIA))


def _score_c(value: Decimal | None) -> Decimal:
    return normalise_growth(value, target=Decimal("0.25"))


def _score_a(value: Decimal | None) -> Decimal:
    return normalise_growth(value, target=Decimal("0.25"))


def _score_n(value: Decimal | None) -> Decimal:
    if value is None:
        return ZERO
    return clip_unit_interval(value)


def _score_s(value: Decimal | None) -> Decimal:
    if value is None:
        return ZERO
    if value >= Decimal("1.5"):
        return ONE
    if value <= ONE:
        return ZERO
    return clip_unit_interval((value - ONE) / Decimal("0.5"))


def _score_l(value: Decimal | None) -> Decimal:
    if value is None:
        return ZERO
    return clip_unit_interval(value / Decimal("100"))


def _score_i(value: Decimal | None) -> Decimal:
    if value is None:
        return Decimal("0.5")
    if value > ZERO:
        return ONE
    if value < ZERO:
        return ZERO
    return Decimal("0.5")


def _score_m(value: Decimal | None) -> Decimal:
    if value is None:
        return ZERO
    return clip_unit_interval(value)


_SCORERS = {
    "C": _score_c,
    "A": _score_a,
    "N": _score_n,
    "S": _score_s,
    "L": _score_l,
    "I": _score_i,
    "M": _score_m,
}


def score(features: Mapping[str, Decimal | None]) -> MethodologyResult:
    """Compute CANSLIM score per O'Neil's 7 criteria."""
    missing: list[str] = []
    pillars: dict[str, PillarScore] = {}

    for criterion in _CRITERIA:
        feature = _FEATURE_BY_CRITERION[criterion]
        raw = features.get(feature)
        if raw is None:
            missing.append(feature)
        s = _SCORERS[criterion](raw)
        pillars[criterion] = PillarScore(name=criterion, score=s, weight=_WEIGHT)

    overall = sum((p.score * p.weight for p in pillars.values()), ZERO)
    overall = clip_unit_interval(overall)

    rationale = (
        "CANSLIM (O'Neil 2002): "
        + ", ".join(f"{c}={pillars[c].score:.2f}" for c in _CRITERIA)
        + f". Composite {overall:.3f}."
    )
    if missing:
        rationale += f" Missing: {', '.join(sorted(set(missing)))}."

    return MethodologyResult(
        overall_score=overall,
        ranking=1,
        pillars=pillars,
        rationale=rationale,
        missing_features=sorted(set(missing)),
    )


__all__ = ["score"]
