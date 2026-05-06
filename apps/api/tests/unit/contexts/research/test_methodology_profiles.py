"""Unit tests for the 5 methodology pure functions (slice R5 Group 2)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from iguanatrader.contexts.research.methodology import METHODOLOGY_REGISTRY
from iguanatrader.contexts.research.methodology.base import MethodologyResult


def _all_high_features() -> dict[str, Decimal | None]:
    """Saturating-positive feature bundle for each methodology."""
    return {
        # 3-pillar
        "eps_growth_yoy": Decimal("0.30"),
        "revenue_growth_yoy": Decimal("0.25"),
        "forward_pe": Decimal("12"),
        "pb_ratio": Decimal("2"),
        "return_3m": Decimal("0.15"),
        "return_12m": Decimal("0.40"),
        "relative_strength": Decimal("0.85"),
        # CANSLIM
        "current_eps_growth_yoy": Decimal("0.40"),
        "annual_eps_growth_3y": Decimal("0.30"),
        "price_at_or_near_52w_high": Decimal("1.0"),
        "volume_surge_ratio": Decimal("2.0"),
        "sector_relative_strength": Decimal("90"),
        "institutional_holding_change_pct": Decimal("0.05"),
        "spy_above_50dma": Decimal("1"),
        # Magic Formula
        "ebit_to_ev": Decimal("0.20"),
        "return_on_capital": Decimal("0.30"),
        # QARP
        "return_on_equity": Decimal("0.25"),
        "return_on_invested_capital": Decimal("0.20"),
        "debt_to_equity": Decimal("0.20"),
        "ev_to_ebitda": Decimal("12"),
        # Multi-factor
        "market_beta": Decimal("1.05"),
        "market_cap_smb_score": Decimal("0.7"),
        "book_to_market": Decimal("0.9"),
        "operating_margin": Decimal("0.30"),
        "capex_to_assets": Decimal("0.05"),
        "return_12m_minus_1": Decimal("0.30"),
    }


@pytest.mark.parametrize("methodology", list(METHODOLOGY_REGISTRY))
def test_methodology_returns_result(methodology: str) -> None:
    score_fn = METHODOLOGY_REGISTRY[methodology]
    result = score_fn(_all_high_features())
    assert isinstance(result, MethodologyResult)
    assert Decimal("0") <= result.overall_score <= Decimal("1")
    assert result.ranking >= 1


@pytest.mark.parametrize("methodology", list(METHODOLOGY_REGISTRY))
def test_methodology_handles_all_missing(methodology: str) -> None:
    score_fn = METHODOLOGY_REGISTRY[methodology]
    result = score_fn({})
    assert result.overall_score == Decimal("0")
    assert len(result.missing_features) > 0


def test_three_pillar_strong_inputs_high_score() -> None:
    score_fn = METHODOLOGY_REGISTRY["three_pillar"]
    result = score_fn(_all_high_features())
    # All 3 pillars saturated → composite ~ 1.0.
    assert result.overall_score >= Decimal("0.8")
    assert "growth" in result.pillars
    assert "value" in result.pillars
    assert "momentum" in result.pillars


def test_canslim_with_failed_market_direction_zeroes_m() -> None:
    score_fn = METHODOLOGY_REGISTRY["canslim"]
    features = _all_high_features() | {"spy_above_50dma": Decimal("0")}
    result = score_fn(features)
    assert result.pillars["M"].score == Decimal("0")


def test_qarp_rejection_filter_zeroes_price_pillar() -> None:
    score_fn = METHODOLOGY_REGISTRY["qarp"]
    features = _all_high_features() | {
        "forward_pe": Decimal("35"),
        "eps_growth_yoy": Decimal("0.10"),
    }
    result = score_fn(features)
    assert result.pillars["reasonable_price"].score == Decimal("0")


def test_magic_formula_reports_pillars() -> None:
    score_fn = METHODOLOGY_REGISTRY["magic_formula"]
    result = score_fn(_all_high_features())
    assert "earnings_yield" in result.pillars
    assert "return_on_capital" in result.pillars


def test_multi_factor_six_pillars_present() -> None:
    score_fn = METHODOLOGY_REGISTRY["multi_factor"]
    result = score_fn(_all_high_features())
    assert set(result.pillars) == {"MKT", "SMB", "HML", "RMW", "CMA", "MOM"}


def test_methodology_registry_has_5_entries() -> None:
    assert len(METHODOLOGY_REGISTRY) == 5
    assert set(METHODOLOGY_REGISTRY) == {
        "three_pillar",
        "canslim",
        "magic_formula",
        "qarp",
        "multi_factor",
    }
