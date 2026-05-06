"""Magic Formula methodology (Joel Greenblatt, 2005).

Two criteria:

* **EBIT/EV** — earnings yield (higher → cheaper).
* **ROC** — return on capital (higher → better business).

Greenblatt's original recipe ranks the universe on each metric
independently and combines via ``rank(EBIT/EV) + rank(ROC)`` (lower
combined rank = better). This pure function operates on a single
symbol's features; the synthesizer's per-watchlist ranker (future R6)
aggregates across the universe. R5 returns a per-symbol score where
each metric is normalised against an absolute reasonable bound.

Citation: Greenblatt, J. (2005). 'The Little Book That Beats the
Market'. Wiley.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from iguanatrader.contexts.research.methodology.base import (
    ZERO,
    MethodologyResult,
    PillarScore,
    clip_unit_interval,
)

_FEATURES = ("ebit_to_ev", "return_on_capital")
_WEIGHT = Decimal("0.5")
_EBIT_EV_TARGET = Decimal("0.15")  # 15% earnings yield = strong
_ROC_TARGET = Decimal("0.25")  # 25% ROC = excellent


def _normalise_yield(value: Decimal | None, *, target: Decimal) -> Decimal:
    if value is None or target <= ZERO:
        return ZERO
    return clip_unit_interval(value / target)


def score(features: Mapping[str, Decimal | None]) -> MethodologyResult:
    """Compute Magic Formula score per Greenblatt's 2 criteria."""
    missing: list[str] = []
    for f in _FEATURES:
        if features.get(f) is None:
            missing.append(f)

    ebit_score = _normalise_yield(features.get("ebit_to_ev"), target=_EBIT_EV_TARGET)
    roc_score = _normalise_yield(features.get("return_on_capital"), target=_ROC_TARGET)

    pillars = {
        "earnings_yield": PillarScore(name="earnings_yield", score=ebit_score, weight=_WEIGHT),
        "return_on_capital": PillarScore(name="return_on_capital", score=roc_score, weight=_WEIGHT),
    }
    overall = clip_unit_interval(ebit_score * _WEIGHT + roc_score * _WEIGHT)

    rationale = (
        f"Magic Formula (Greenblatt 2005): "
        f"EBIT/EV-yield={ebit_score:.3f}, ROC={roc_score:.3f}. Composite {overall:.3f}."
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
