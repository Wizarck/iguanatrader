"""Robust parsing of the audit_trail_entries JSON block in LLM output.

Production bug observed 2026-05-17: a real NVDA brief hit
``MAX_OUTPUT_TOKENS=2000`` mid-block and never emitted the closing
` ``` ` fence. The lazy regex failed to match → no entries extracted
→ the unparsed JSON tail bled into the rendered body as raw text.

This test suite locks in the recovered behaviour:

* complete fenced block → strip + parse normally
* truncated fenced block (no closer) → strip from opener to EOF, attempt
  best-effort JSON salvage by appending closing brackets
* no fence at all → body unchanged, empty entries
"""

from __future__ import annotations

from iguanatrader.contexts.research.synthesis.synthesizer import Synthesizer


def test_complete_fenced_block_is_stripped_and_parsed() -> None:
    body_prose = "## Growth\n\nNVDA grew revenue 66%.\n\n"
    json_block = (
        "```json\n"
        '{"audit_trail_entries": ['
        '{"metric": "eps_growth_yoy", "formula": "x", "inputs": [], "steps": [],'
        ' "final_output": "66% YoY"}'
        "]}\n"
        "```"
    )
    body, entries = Synthesizer._parse_output(body_prose + json_block)
    assert "```json" not in body
    assert "audit_trail_entries" not in body
    assert body.strip().endswith("66%.")
    assert len(entries) == 1
    assert entries[0].metric == "eps_growth_yoy"


def test_truncated_block_no_closing_fence_is_still_stripped() -> None:
    body_prose = "## Value\n\nP/B elevated.\n\n---\n\n"
    truncated = (
        "```json\n"
        '{"audit_trail_entries": [\n'
        '  {"metric": "forward_pe", "formula": "P/E_fwd", "inputs": [], "steps": [],'
        ' "final_output": "24.0"},\n'
        '  {"metric": "pb_ratio", "formula": "P/B", "inputs": [], "steps": [],'
        ' "final_output": "3.2"'
    )
    body, entries = Synthesizer._parse_output(body_prose + truncated)
    assert "```json" not in body
    assert "audit_trail_entries" not in body
    assert "P/B elevated." in body
    # Best-effort salvage recovers the first complete entry.
    assert any(e.metric == "forward_pe" for e in entries)


def test_truncated_unrecoverable_block_still_strips_dangling_json() -> None:
    body_prose = "## Momentum\n\nStrong RS.\n\n"
    # Garbage right after opener — can't salvage entries but must strip.
    truncated = '```json\n{"audit_trail_entries": [{"metric": broken'
    body, entries = Synthesizer._parse_output(body_prose + truncated)
    assert "```json" not in body
    assert "audit_trail_entries" not in body
    assert "Strong RS." in body
    assert entries == []


def test_no_fence_returns_body_unchanged() -> None:
    body_prose = (
        "## Growth\n\nNVDA grew revenue.\n\n## Value\n\nP/B elevated.\n\n"
        "## Momentum\n\nStrong RS."
    )
    body, entries = Synthesizer._parse_output(body_prose)
    assert body == body_prose.strip()
    assert entries == []
