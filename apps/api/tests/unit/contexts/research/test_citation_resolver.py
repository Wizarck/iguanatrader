"""Unit tests for CitationResolver (slice R5 D4)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from iguanatrader.contexts.research.synthesis.citation_resolver import (
    CitationResolver,
    _summarise_fact_value,
)


def test_parse_markers_extracts_canonical_uuids() -> None:
    body = (
        "P/E ratio is 18.5 [fact:11111111-1111-1111-1111-111111111111] "
        "and EPS growth 25% [fact:22222222-2222-2222-2222-222222222222]."
    )
    markers = CitationResolver.parse_markers(body)
    assert markers == [
        UUID("11111111-1111-1111-1111-111111111111"),
        UUID("22222222-2222-2222-2222-222222222222"),
    ]


def test_parse_markers_deduplicates() -> None:
    body = (
        "[fact:11111111-1111-1111-1111-111111111111] " "[fact:11111111-1111-1111-1111-111111111111]"
    )
    assert len(CitationResolver.parse_markers(body)) == 1


def test_parse_markers_case_insensitive() -> None:
    body = "[fact:AAAAAAAA-1111-1111-1111-111111111111]"
    markers = CitationResolver.parse_markers(body)
    assert len(markers) == 1


def test_parse_markers_skips_malformed() -> None:
    body = "[fact:not-a-uuid] [fact:11111111-1111-1111-1111-111111111111]"
    markers = CitationResolver.parse_markers(body)
    assert len(markers) == 1


def test_parse_markers_empty_body() -> None:
    assert CitationResolver.parse_markers("") == []
    assert CitationResolver.parse_markers("Plain prose with no markers.") == []


def test_validate_against_bundle_flags_invented_uuids() -> None:
    body = (
        "[fact:11111111-1111-1111-1111-111111111111] " "[fact:22222222-2222-2222-2222-222222222222]"
    )
    allowed = {UUID("11111111-1111-1111-1111-111111111111")}
    invalid = CitationResolver.validate_against_bundle(body, allowed)
    assert invalid == [UUID("22222222-2222-2222-2222-222222222222")]


def test_validate_against_bundle_passes_when_all_match() -> None:
    body = "[fact:11111111-1111-1111-1111-111111111111]"
    allowed = {UUID("11111111-1111-1111-1111-111111111111")}
    assert CitationResolver.validate_against_bundle(body, allowed) == []


# ---------------------------------------------------------------------------
# _summarise_fact_value (slice citation-chip-enrichment, 2026-05-18)
#
# Drives the ``value_excerpt`` shipped to the frontend so citation chips
# can display WHAT the fact says, not just where it came from.
# ---------------------------------------------------------------------------


@dataclass
class _FactStub:
    """Duck-typed stand-in for ResearchFact — only the fields the
    summariser reads. Keeps the test free of DB setup."""

    value_numeric: Decimal | None = None
    value_text: str | None = None
    value_jsonb: Any | None = None
    unit: str | None = None
    currency: str | None = None
    fact_kind: str = ""


def test_summarise_prefers_numeric_with_currency() -> None:
    fact = _FactStub(value_numeric=Decimal("164.50"), currency="USD")
    assert _summarise_fact_value(fact) == "164.50 USD"  # type: ignore[arg-type]


def test_summarise_numeric_with_unit_when_no_currency() -> None:
    fact = _FactStub(value_numeric=Decimal("0.85"), unit="ratio")
    assert _summarise_fact_value(fact) == "0.85 ratio"  # type: ignore[arg-type]


def test_summarise_numeric_no_suffix_when_neither() -> None:
    fact = _FactStub(value_numeric=Decimal("12345"))
    assert _summarise_fact_value(fact) == "12345"  # type: ignore[arg-type]


def test_summarise_falls_back_to_text() -> None:
    fact = _FactStub(value_text="Q1 beat estimates by 12%")
    assert _summarise_fact_value(fact) == "Q1 beat estimates by 12%"  # type: ignore[arg-type]


def test_summarise_clips_long_text() -> None:
    fact = _FactStub(value_text="a" * 200)
    out = _summarise_fact_value(fact)  # type: ignore[arg-type]
    assert len(out) == 60
    assert out.endswith("…")


def test_summarise_single_key_dict_inlines_value() -> None:
    fact = _FactStub(value_jsonb={"value": 164.5})
    assert _summarise_fact_value(fact) == "164.5"  # type: ignore[arg-type]


def test_summarise_fundamentals_surfaces_forward_pe() -> None:
    # Multi-key dict + known fact_kind → return the primary scalar
    # ("forward_pe=30.2") instead of the previous opaque keys dump.
    fact = _FactStub(
        fact_kind="fundamentals",
        value_jsonb={"forward_pe": 30.2, "pe_ratio": 28.4, "price_to_book": 12.3},
    )
    assert _summarise_fact_value(fact) == "forward_pe=30.2"  # type: ignore[arg-type]


def test_summarise_analyst_ratings_surfaces_target() -> None:
    fact = _FactStub(
        fact_kind="analyst_ratings",
        value_jsonb={"analyst_target_price": 164.5, "analyst_count": 25},
    )
    assert _summarise_fact_value(fact) == "analyst_target_price=164.5"  # type: ignore[arg-type]


def test_summarise_unknown_multi_key_dict_returns_empty() -> None:
    # An unfamiliar multi-key shape with no known primary scalar — chip
    # falls back to fact_kind alone instead of leaking the keys list.
    fact = _FactStub(
        fact_kind="historical_prices_window",
        value_jsonb={"symbol": "NVDA", "start_date": "2025-04-01", "bars": 250},
    )
    assert _summarise_fact_value(fact) == ""  # type: ignore[arg-type]


def test_summarise_list_reports_length() -> None:
    fact = _FactStub(value_jsonb={"prices": [1, 2, 3, 4, 5]})
    # Single-key dict → unwraps to the list value, which then str()s.
    out = _summarise_fact_value(fact)  # type: ignore[arg-type]
    assert "[" in out


def test_summarise_empty_when_no_value() -> None:
    fact = _FactStub()
    assert _summarise_fact_value(fact) == ""  # type: ignore[arg-type]


def test_summarise_numeric_wins_over_jsonb() -> None:
    fact = _FactStub(value_numeric=Decimal("42"), value_jsonb={"x": 1})
    assert _summarise_fact_value(fact) == "42"  # type: ignore[arg-type]


def test_summarise_rounds_jsonb_primary_scalar_to_two_decimals() -> None:
    # 32.73839 → 32.74; trailing zeros stripped (`32.7` not `32.70`).
    fact = _FactStub(
        fact_kind="fundamentals",
        value_jsonb={"forward_pe": 32.73839, "pe_ratio": 28.0, "price_to_book": 12.3},
    )
    assert _summarise_fact_value(fact) == "forward_pe=32.74"  # type: ignore[arg-type]


def test_summarise_historical_prices_extracts_last_close() -> None:
    fact = _FactStub(
        fact_kind="historical_prices_window",
        value_jsonb={
            "symbol": "AMD",
            "bars": [
                {"date": "2026-05-14", "close": 420.0},
                {"date": "2026-05-15", "close": 424.10},
            ],
        },
    )
    assert _summarise_fact_value(fact) == "last=424.1 @ 2026-05-15"  # type: ignore[arg-type]


def test_summarise_historical_prices_empty_bars_returns_empty() -> None:
    fact = _FactStub(fact_kind="historical_prices_window", value_jsonb={"bars": []})
    assert _summarise_fact_value(fact) == ""  # type: ignore[arg-type]
