"""Unit tests for CitationResolver (slice R5 D4)."""

from __future__ import annotations

from uuid import UUID

from iguanatrader.contexts.research.synthesis.citation_resolver import CitationResolver


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
