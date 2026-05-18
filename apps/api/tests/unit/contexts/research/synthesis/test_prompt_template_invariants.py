"""Prompt template invariants (slice methodology-low-confidence, 2026-05-18).

These tests pin the structural rules baked into the methodology
prompt templates. They are LIGHT regression sentinels — not a
guarantee the LLM will obey, but they catch the case where a
template edit accidentally drops a load-bearing instruction.

The trigger for this slice was a real-world AMD brief that emitted
``Action: AVOID`` purely because tier-A data was missing (composite
was ~0.33 due to a 0.000 growth pillar). Missing data is NOT a sell
signal — it is "insufficient information to decide". The three_pillar
template now treats partial data as a HOLD low-confidence override
ahead of the score-based mapping.
"""

from __future__ import annotations

from iguanatrader.contexts.research.synthesis.synthesizer import PROMPT_DIR


def test_three_pillar_template_has_data_sufficiency_override() -> None:
    text = (PROMPT_DIR / "three_pillar.md").read_text(encoding="utf-8")
    # The override must (a) name the rule, (b) say it's highest
    # precedence, and (c) state that missing data is NOT a sell signal.
    assert "Data-sufficiency override" in text
    assert "highest precedence" in text
    assert "Missing data is NOT a sell signal" in text


def test_three_pillar_template_still_lists_score_mapping() -> None:
    """The score-based mapping must remain present for the populated
    case — the override only fires when tier-A is missing."""
    text = (PROMPT_DIR / "three_pillar.md").read_text(encoding="utf-8")
    assert "≥0.65 → BUY" in text
    assert "0.40-0.64 → HOLD" in text
    assert "<0.40 → AVOID" in text


def test_three_pillar_template_keeps_recommendation_section_mandatory() -> None:
    """``## Recommendation`` is the section the BriefHeader hangs the
    Configure-strategy CTA off of; do not let it become optional."""
    text = (PROMPT_DIR / "three_pillar.md").read_text(encoding="utf-8")
    assert "`## Recommendation`" in text
    assert "mandatory and MUST come first" in text
