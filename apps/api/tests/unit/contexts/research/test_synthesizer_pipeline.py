"""Unit tests for the brief synthesizer pipeline (slice R5 D3)."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from iguanatrader.contexts.research.errors import (
    BriefSynthesisShortError,
    InvalidCitationError,
)
from iguanatrader.contexts.research.feature_provider.base import FeatureBundle
from iguanatrader.contexts.research.methodology import METHODOLOGY_REGISTRY
from iguanatrader.contexts.research.synthesis.llm_client import FakeLLMClient
from iguanatrader.contexts.research.synthesis.synthesizer import (
    MIN_BODY_WORDS,
    Synthesizer,
)


def _bundle_with_one_citation() -> FeatureBundle:
    fid = UUID("11111111-1111-1111-1111-111111111111")
    return FeatureBundle(
        values={
            "eps_growth_yoy": (Decimal("0.30"), "A"),
            "revenue_growth_yoy": (Decimal("0.25"), "A"),
            "forward_pe": (Decimal("12"), "B"),
            "pb_ratio": (Decimal("2"), "B"),
            "return_3m": (Decimal("0.10"), "A"),
            "return_12m": (Decimal("0.30"), "A"),
            "relative_strength": (Decimal("0.85"), "A"),
        },
        fact_citations={"eps_growth_yoy": fid},
    )


def _long_body() -> str:
    """Generate a body well above the 100-word floor."""
    word = "alpha"
    paragraph = " ".join([word] * (MIN_BODY_WORDS + 20))
    return f"## Growth\n\n{paragraph}\n\n[fact:11111111-1111-1111-1111-111111111111]"


@pytest.mark.asyncio
async def test_synthesize_returns_brief_with_pillars() -> None:
    bundle = _bundle_with_one_citation()
    methodology_result = METHODOLOGY_REGISTRY["three_pillar"](bundle.values_only())
    fake = FakeLLMClient()
    key = Synthesizer._compute_replay_key(
        symbol="AAPL", methodology="three_pillar", feature_bundle=bundle
    )
    fake.register(key, _long_body())
    synth = Synthesizer(llm_client=fake)
    result = await synth.synthesize(
        symbol="AAPL",
        methodology="three_pillar",
        feature_bundle=bundle,
        methodology_result=methodology_result,
        model="claude-3-5-sonnet",
    )
    assert "growth" in result.pillars
    assert result.overall_score == methodology_result.overall_score
    assert result.citations_used  # at least one fact:<uuid> marker present


@pytest.mark.asyncio
async def test_synthesize_rejects_invented_uuid() -> None:
    bundle = _bundle_with_one_citation()
    methodology_result = METHODOLOGY_REGISTRY["three_pillar"](bundle.values_only())
    fake = FakeLLMClient()
    invented_body = (
        "## Growth\n\n" + ("alpha " * 110) + "[fact:99999999-9999-9999-9999-999999999999]"
    )
    # Inject the body directly via replay registry — synthesizer asks
    # the fake by replay_key, which it computes deterministically.
    key = Synthesizer._compute_replay_key(
        symbol="AAPL", methodology="three_pillar", feature_bundle=bundle
    )
    fake.register(key, invented_body)
    synth = Synthesizer(llm_client=fake)
    with pytest.raises(InvalidCitationError):
        await synth.synthesize(
            symbol="AAPL",
            methodology="three_pillar",
            feature_bundle=bundle,
            methodology_result=methodology_result,
            model="claude-3-5-sonnet",
        )


@pytest.mark.asyncio
async def test_synthesize_rejects_short_body() -> None:
    bundle = _bundle_with_one_citation()
    methodology_result = METHODOLOGY_REGISTRY["three_pillar"](bundle.values_only())
    fake = FakeLLMClient()
    key = Synthesizer._compute_replay_key(
        symbol="AAPL", methodology="three_pillar", feature_bundle=bundle
    )
    fake.register(key, "Too short.")
    synth = Synthesizer(llm_client=fake)
    with pytest.raises(BriefSynthesisShortError):
        await synth.synthesize(
            symbol="AAPL",
            methodology="three_pillar",
            feature_bundle=bundle,
            methodology_result=methodology_result,
            model="claude-3-5-sonnet",
        )


def test_compute_replay_key_is_deterministic() -> None:
    bundle = _bundle_with_one_citation()
    k1 = Synthesizer._compute_replay_key(
        symbol="AAPL", methodology="canslim", feature_bundle=bundle
    )
    k2 = Synthesizer._compute_replay_key(
        symbol="AAPL", methodology="canslim", feature_bundle=bundle
    )
    assert k1 == k2
    assert k1.startswith("brief:AAPL:canslim:")


def test_parse_output_extracts_audit_trail_block() -> None:
    body = (
        "## Growth\n\nGrowth narrative here.\n\n"
        '```json\n{"audit_trail_entries": [{"metric": "forward_pe", '
        '"formula": "price / forward_eps", "inputs": [], "steps": [], '
        '"final_output": "18.5"}]}\n```\n'
    )
    body_clean, entries = Synthesizer._parse_output(body)
    assert "Growth narrative" in body_clean
    assert "json" not in body_clean.lower()
    assert len(entries) == 1
    assert entries[0].metric == "forward_pe"


def test_parse_output_strips_partial_true_prose_marker() -> None:
    """Slice brief-ui-cleanup (2026-05-18): the prompt instructs the LLM
    to emit ``partial=true`` somewhere in its response when tier-A is
    missing. The synthesizer detects the flag via :meth:`_is_partial_in_text`
    BEFORE the body is rendered, but the literal marker used to leak
    through as visible prose (operator-facing garbage). The parser
    must scrub it from the body."""
    body = "partial=true\n\n" "## Recommendation\n\n**Action**: HOLD\n\n" "Some growth analysis.\n"
    body_clean, _entries = Synthesizer._parse_output(body)
    assert "partial=true" not in body_clean
    assert "## Recommendation" in body_clean
    assert "**Action**: HOLD" in body_clean


def test_parse_output_strips_partial_true_with_audit_trail() -> None:
    body = "## Thesis\n\nNarrative.\npartial=true\n\n" '```json\n{"audit_trail_entries": []}\n```\n'
    body_clean, _entries = Synthesizer._parse_output(body)
    assert "partial=true" not in body_clean
    assert "Narrative." in body_clean
