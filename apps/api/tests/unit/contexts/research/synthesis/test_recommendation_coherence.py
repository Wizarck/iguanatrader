"""Unit tests for the recommendation-coherence checker (slice
``llm-brief-coherence``).

Validates the post-LLM-parse pure-function check that flags briefs
where the Action (BUY/HOLD/AVOID) contradicts the Target price's
direction relative to current close. Pure-unit — no LLM, no DB.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from iguanatrader.contexts.research.feature_provider.base import (
    FeatureBundle,
    FeatureValue,
)
from iguanatrader.contexts.research.synthesis.synthesizer import (
    _check_recommendation_coherence,
)


def _bundle(close_price: Decimal | None) -> FeatureBundle:
    values: dict[str, FeatureValue] = {
        "close_price": (close_price, "A"),
        "eps_diluted": (Decimal("3.50"), "A"),
    }
    citations = {"close_price": uuid4()} if close_price is not None else {}
    return FeatureBundle(values=values, fact_citations=citations)


def _brief(action: str, target: str) -> str:
    return (
        "## Recommendation\n\n"
        f"**Action**: {action}\n\n"
        f"**Target price**: ${target}\n\n"
        "**Horizon**: 12 months\n\n"
        "**Key risks**: - elevated multiples\n"
    )


# ---------------------------------------------------------------------------
# Coherent cases
# ---------------------------------------------------------------------------


def test_buy_with_target_above_price_is_coherent() -> None:
    res = _check_recommendation_coherence(
        symbol="NVDA",
        body_markdown=_brief("BUY", "625.00"),
        feature_bundle=_bundle(Decimal("424.10")),
    )
    assert res is True


def test_avoid_with_target_below_price_is_coherent() -> None:
    res = _check_recommendation_coherence(
        symbol="ZZZ",
        body_markdown=_brief("AVOID", "85.00"),
        feature_bundle=_bundle(Decimal("100.00")),
    )
    assert res is True


def test_hold_with_target_within_tolerance_is_coherent() -> None:
    """HOLD allows +/- 15 % around the current price."""
    res = _check_recommendation_coherence(
        symbol="SPY",
        body_markdown=_brief("HOLD", "108.00"),
        feature_bundle=_bundle(Decimal("100.00")),
    )
    assert res is True


def test_buy_equal_to_price_is_coherent() -> None:
    """Edge case: target == current is still BUY-compatible (no downside)."""
    res = _check_recommendation_coherence(
        symbol="EDGE",
        body_markdown=_brief("BUY", "100.00"),
        feature_bundle=_bundle(Decimal("100.00")),
    )
    assert res is True


# ---------------------------------------------------------------------------
# Incoherent cases (the AMD-style bug we are fixing)
# ---------------------------------------------------------------------------


def test_buy_with_target_below_price_is_incoherent() -> None:
    """The AMD bug: composite says BUY, LLM emits target $210, current $424."""
    res = _check_recommendation_coherence(
        symbol="AMD",
        body_markdown=_brief("BUY", "210.00"),
        feature_bundle=_bundle(Decimal("424.10")),
    )
    assert res is False


def test_avoid_with_target_above_price_is_incoherent() -> None:
    res = _check_recommendation_coherence(
        symbol="XYZ",
        body_markdown=_brief("AVOID", "150.00"),
        feature_bundle=_bundle(Decimal("100.00")),
    )
    assert res is False


def test_hold_with_target_far_above_tolerance_is_incoherent() -> None:
    """HOLD with target 30 % above current — outside ±15 % band."""
    res = _check_recommendation_coherence(
        symbol="ABC",
        body_markdown=_brief("HOLD", "130.00"),
        feature_bundle=_bundle(Decimal("100.00")),
    )
    assert res is False


def test_hold_with_target_far_below_tolerance_is_incoherent() -> None:
    res = _check_recommendation_coherence(
        symbol="ABC",
        body_markdown=_brief("HOLD", "75.00"),
        feature_bundle=_bundle(Decimal("100.00")),
    )
    assert res is False


# ---------------------------------------------------------------------------
# Cannot-validate (returns None) cases
# ---------------------------------------------------------------------------


def test_missing_close_price_returns_none() -> None:
    """Without a current price anchor the checker abstains — the brief
    proceeds with whatever flag the rest of the pipeline already set."""
    res = _check_recommendation_coherence(
        symbol="NEW",
        body_markdown=_brief("BUY", "120.00"),
        feature_bundle=_bundle(None),
    )
    assert res is None


def test_close_price_zero_returns_none() -> None:
    """Division-by-zero guard."""
    res = _check_recommendation_coherence(
        symbol="ZERO",
        body_markdown=_brief("BUY", "10.00"),
        feature_bundle=_bundle(Decimal("0")),
    )
    assert res is None


def test_missing_action_in_brief_returns_none() -> None:
    body = "## Recommendation\n\n**Target price**: $150.00\n"  # no Action line
    res = _check_recommendation_coherence(
        symbol="WHAT",
        body_markdown=body,
        feature_bundle=_bundle(Decimal("100.00")),
    )
    assert res is None


def test_missing_target_in_brief_returns_none() -> None:
    body = "## Recommendation\n\n**Action**: BUY\n"  # no Target line
    res = _check_recommendation_coherence(
        symbol="WHAT",
        body_markdown=body,
        feature_bundle=_bundle(Decimal("100.00")),
    )
    assert res is None


def test_unparseable_target_value_returns_none() -> None:
    body = "## Recommendation\n\n**Action**: BUY\n\n**Target price**: see analyst note\n"
    res = _check_recommendation_coherence(
        symbol="WHAT",
        body_markdown=body,
        feature_bundle=_bundle(Decimal("100.00")),
    )
    assert res is None


# ---------------------------------------------------------------------------
# Real-world brief shape — make sure the regexes survive prompt prose
# ---------------------------------------------------------------------------


def test_amd_style_brief_with_trailing_prose_is_incoherent() -> None:
    """Mirrors the actual prompt output shape with bullet risks + JSON
    block trailing; regexes must skip past the rest."""
    body = (
        "## Recommendation\n\n"
        "**Action**: BUY\n\n"
        "**Target price**: $210.00 (12-month horizon)\n\n"
        "**Horizon**: 12 months\n\n"
        "**Key risks**:\n"
        "- elevated valuation multiples (forward P/E ~32.7x)\n"
        "- semiconductor cycle volatility\n\n"
        "## Growth\n\nLong prose about EPS expansion.\n\n"
        '```json\n{"audit_trail_entries": []}\n```\n'
    )
    res = _check_recommendation_coherence(
        symbol="AMD",
        body_markdown=body,
        feature_bundle=_bundle(Decimal("424.10")),
    )
    assert res is False


def test_buy_with_comma_separated_target_parses() -> None:
    """Targets sometimes get formatted with thousands separators."""
    body = "## Recommendation\n\n**Action**: BUY\n\n**Target price**: $1,250.00\n"
    res = _check_recommendation_coherence(
        symbol="GOOGL",
        body_markdown=body,
        feature_bundle=_bundle(Decimal("1000.00")),
    )
    assert res is True
