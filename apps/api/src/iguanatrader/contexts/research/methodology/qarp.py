"""QARP — Quality At Reasonable Price (slice R5 design D1).

Synthesis of GMO and AQR research. Two factor groups:

* **Quality** — ``return_on_equity``, ``return_on_invested_capital``,
  ``debt_to_equity`` (lower → higher quality; capped at 1.5).
* **Reasonable price** — ``forward_pe``, ``ev_to_ebitda`` (both lower
  → cheaper; rejected if ``forward_pe > 30`` AND ``eps_growth_yoy <= 0.20``).

Reference: GMO White Papers + AQR Quality Minus Junk (2014).
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
    normalise_inverse_pe,
)

_QUALITY_FEATURES = ("return_on_equity", "return_on_invested_capital", "debt_to_equity")
_PRICE_FEATURES = ("forward_pe", "ev_to_ebitda")
_QUALITY_WEIGHT = Decimal("0.6")
_PRICE_WEIGHT = Decimal("0.4")


def _score_roe(value: Decimal | None) -> Decimal:
    if value is None:
        return ZERO
    return clip_unit_interval(value / Decimal("0.20"))


def _score_roic(value: Decimal | None) -> Decimal:
    if value is None:
        return ZERO
    return clip_unit_interval(value / Decimal("0.20"))


def _score_debt_to_equity(value: Decimal | None) -> Decimal:
    if value is None:
        return ZERO
    if value < ZERO:
        return ONE  # negative net debt (cash > debt) is excellent.
    return clip_unit_interval(ONE - (value / Decimal("1.5")))


def score(features: Mapping[str, Decimal | None]) -> MethodologyResult:
    """Compute QARP score with quality + reasonable-price filter."""
    missing: list[str] = []
    for f in _QUALITY_FEATURES + _PRICE_FEATURES:
        if features.get(f) is None:
            missing.append(f)

    roe = _score_roe(features.get("return_on_equity"))
    roic = _score_roic(features.get("return_on_invested_capital"))
    debt = _score_debt_to_equity(features.get("debt_to_equity"))
    quality_score = (roe + roic + debt) / Decimal(len(_QUALITY_FEATURES))

    pe_score = normalise_inverse_pe(features.get("forward_pe"), max_pe=Decimal("30"))
    ev_score = normalise_inverse_pe(features.get("ev_to_ebitda"), max_pe=Decimal("20"))
    price_score = (pe_score + ev_score) / Decimal(len(_PRICE_FEATURES))

    # Reasonable-price rejection filter: high forward_pe with sub-20% growth
    # zeroes the price-pillar.
    fwd_pe = features.get("forward_pe")
    eps_growth = features.get("eps_growth_yoy")
    if (
        fwd_pe is not None
        and eps_growth is not None
        and fwd_pe > Decimal("30")
        and eps_growth <= Decimal("0.20")
    ):
        price_score = ZERO

    pillars = {
        "quality": PillarScore(
            name="quality", score=clip_unit_interval(quality_score), weight=_QUALITY_WEIGHT
        ),
        "reasonable_price": PillarScore(
            name="reasonable_price", score=clip_unit_interval(price_score), weight=_PRICE_WEIGHT
        ),
    }
    overall = clip_unit_interval(quality_score * _QUALITY_WEIGHT + price_score * _PRICE_WEIGHT)

    rationale = (
        f"QARP: quality={pillars['quality'].score:.3f} "
        f"(weight {_QUALITY_WEIGHT}), reasonable_price={pillars['reasonable_price'].score:.3f} "
        f"(weight {_PRICE_WEIGHT}). Composite {overall:.3f}."
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
