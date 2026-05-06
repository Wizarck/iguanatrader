"""Multi-factor methodology — Fama-French 5-factor + momentum.

Citation: Fama, E. F., & French, K. R. (2015). 'A five-factor asset
pricing model'. Journal of Financial Economics, 116(1), 1-22.

Five factors:

* **MKT** (market beta): centred at 1.0 — closer-to-1 → 1.0; abs deviation
  reduces score linearly.
* **SMB** (size): smaller market cap is the SMB premium (``market_cap_smb_score``,
  pre-computed, 0-1 normalised).
* **HML** (value): high book-to-market is the HML premium
  (``book_to_market`` scaled to ``[0, 1]`` via target 1.0).
* **RMW** (profitability): robust profitability via ``operating_margin``
  scaled by target 0.30.
* **CMA** (investment): conservative investment via ``capex_to_assets``
  scaled INVERSELY (lower CMA → higher score).

Plus 1 custom **MOM** (momentum): ``return_12m_minus_1`` (12m return
excluding most recent month — the canonical academic momentum factor).
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

_FACTORS = ("MKT", "SMB", "HML", "RMW", "CMA", "MOM")
_FEATURE_BY_FACTOR = {
    "MKT": "market_beta",
    "SMB": "market_cap_smb_score",
    "HML": "book_to_market",
    "RMW": "operating_margin",
    "CMA": "capex_to_assets",
    "MOM": "return_12m_minus_1",
}
_WEIGHT = ONE / Decimal(len(_FACTORS))


def _score_mkt(value: Decimal | None) -> Decimal:
    if value is None:
        return ZERO
    deviation = abs(value - ONE)
    return clip_unit_interval(ONE - deviation)


def _score_smb(value: Decimal | None) -> Decimal:
    if value is None:
        return ZERO
    return clip_unit_interval(value)


def _score_hml(value: Decimal | None) -> Decimal:
    return normalise_growth(value, target=ONE)


def _score_rmw(value: Decimal | None) -> Decimal:
    return normalise_growth(value, target=Decimal("0.30"))


def _score_cma(value: Decimal | None) -> Decimal:
    if value is None:
        return ZERO
    return clip_unit_interval(ONE - (value / Decimal("0.20")))


def _score_mom(value: Decimal | None) -> Decimal:
    return normalise_growth(value, target=Decimal("0.30"))


_SCORERS = {
    "MKT": _score_mkt,
    "SMB": _score_smb,
    "HML": _score_hml,
    "RMW": _score_rmw,
    "CMA": _score_cma,
    "MOM": _score_mom,
}


def score(features: Mapping[str, Decimal | None]) -> MethodologyResult:
    """Compute multi-factor (Fama-French 5 + momentum) score."""
    missing: list[str] = []
    pillars: dict[str, PillarScore] = {}

    for factor in _FACTORS:
        feature_name = _FEATURE_BY_FACTOR[factor]
        raw = features.get(feature_name)
        if raw is None:
            missing.append(feature_name)
        s = _SCORERS[factor](raw)
        pillars[factor] = PillarScore(name=factor, score=s, weight=_WEIGHT)

    overall = clip_unit_interval(sum((p.score * p.weight for p in pillars.values()), ZERO))

    rationale = (
        "Multi-factor (Fama-French 5 + MOM): "
        + ", ".join(f"{f}={pillars[f].score:.2f}" for f in _FACTORS)
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
