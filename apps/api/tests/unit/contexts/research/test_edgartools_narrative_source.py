"""Unit tests for the edgartools 10-K narrative adapter (slice I6).

Pure-unit — no edgartools install required, no SEC EDGAR network. A
fake ``company_resolver`` returns canned filings shaped after the
edgartools attribute / method surface so we can validate URL
composition, section selection, ConfigError when the lib is missing,
and the empty-section degradation path.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from iguanatrader.contexts.research.errors import ConfigError, SourceUnavailableError
from iguanatrader.contexts.research.sources.edgartools_narrative import (
    SECTION_MDNA,
    SECTION_RISK,
    EdgartoolsSource,
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class _FakeFiling:
    """Stand-in for an edgartools Filing — exposes the attribute shapes
    the adapter probes."""

    def __init__(
        self,
        *,
        accession: str = "0001234567-25-000001",
        filing_date: datetime | None = None,
        mdna: str = "",
        risk: str = "",
        url: str = "",
    ) -> None:
        self.accession_number = accession
        self.filing_date = filing_date or datetime(2026, 3, 15, tzinfo=UTC)
        self.filing_url = (
            url
            or f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000320193&accession={accession}"
        )
        # Probe 1: structured tenK accessor (canonical edgartools shape).
        self.tenK = _FakeTenK(mdna=mdna, risk=risk)


class _FakeTenK:
    def __init__(self, *, mdna: str, risk: str) -> None:
        self.mdna = mdna
        self.risk_factors = risk


class _FakeCompany:
    """Stand-in for ``edgartools.Company`` — exposes ``get_filings``."""

    def __init__(self, *, filings: list[_FakeFiling]) -> None:
        self._filings = filings

    def get_filings(
        self, *, form: str | None = None, accession_number: str | None = None
    ) -> list[_FakeFiling]:
        if accession_number is not None:
            return [f for f in self._filings if f.accession_number == accession_number]
        if form == "10-K":
            return list(self._filings)
        return []


def _resolver(filings: list[_FakeFiling]) -> Any:
    def _build(_ticker: str) -> _FakeCompany:
        return _FakeCompany(filings=filings)

    return _build


# ---------------------------------------------------------------------------
# Construction / lazy-import gating
# ---------------------------------------------------------------------------


def test_construct_raises_configerror_when_edgartools_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No company_resolver injected → lazy import of edgartools triggers.
    The dep isn't installed in CI, so this must surface a typed ConfigError
    with installation hints rather than a raw ImportError stack."""
    # Force ImportError by removing edgartools if it sneaked in.
    monkeypatch.setattr(
        "iguanatrader.contexts.research.sources.edgartools_narrative.EdgartoolsSource",
        EdgartoolsSource,
    )
    # The default branch only fires when company_resolver=None; the import
    # in that branch fails at import time when edgartools isn't installed.
    with pytest.raises(ConfigError, match=r"edgartools is not installed|pip install"):
        EdgartoolsSource()


def test_construct_with_injected_resolver_skips_lazy_import() -> None:
    """A test-injected resolver bypasses the lazy import; constructor
    must NOT touch edgartools."""
    source = EdgartoolsSource(company_resolver=_resolver([]))
    assert source is not None


# ---------------------------------------------------------------------------
# Section selection / contract
# ---------------------------------------------------------------------------


def test_unknown_section_raises_value_error() -> None:
    source = EdgartoolsSource(company_resolver=_resolver([]))
    with pytest.raises(ValueError, match="Unknown edgartools section"):
        _run(source.fetch_narrative_async(ticker_or_cik="AAPL", include=["bogus"]))


def test_no_filing_raises_source_unavailable() -> None:
    source = EdgartoolsSource(company_resolver=_resolver([]))
    with pytest.raises(SourceUnavailableError, match="could not resolve a 10-K"):
        _run(source.fetch_narrative_async(ticker_or_cik="ZZZZ"))


# ---------------------------------------------------------------------------
# Draft shape — happy path
# ---------------------------------------------------------------------------


def test_default_include_returns_both_sections() -> None:
    filings = [_FakeFiling(mdna="MD&A prose here.", risk="Risk factors prose here.")]
    source = EdgartoolsSource(company_resolver=_resolver(filings))
    drafts = _run(source.fetch_narrative_async(ticker_or_cik="AAPL", symbol="AAPL"))
    kinds = {d.fact_kind for d in drafts}
    assert kinds == {"sec_text.mdna", "sec_text.risk_factors"}
    assert all(d.source_id == "edgartools-narrative" for d in drafts)


def test_include_mdna_only() -> None:
    filings = [_FakeFiling(mdna="Only MD&A.", risk="should not appear")]
    source = EdgartoolsSource(company_resolver=_resolver(filings))
    drafts = _run(
        source.fetch_narrative_async(ticker_or_cik="AAPL", symbol="AAPL", include=[SECTION_MDNA])
    )
    assert len(drafts) == 1
    assert drafts[0].fact_kind == "sec_text.mdna"
    assert drafts[0].value_text == "Only MD&A."


def test_include_risk_only() -> None:
    filings = [_FakeFiling(mdna="should not appear", risk="Only Risk.")]
    source = EdgartoolsSource(company_resolver=_resolver(filings))
    drafts = _run(
        source.fetch_narrative_async(ticker_or_cik="AAPL", symbol="AAPL", include=[SECTION_RISK])
    )
    assert len(drafts) == 1
    assert drafts[0].fact_kind == "sec_text.risk_factors"


def test_empty_section_degrades_silently() -> None:
    """A 10-K missing one section (some filers split filings) must
    yield no draft for that section, while the other still ships."""
    filings = [_FakeFiling(mdna="Has MD&A", risk="")]
    source = EdgartoolsSource(company_resolver=_resolver(filings))
    drafts = _run(source.fetch_narrative_async(ticker_or_cik="AAPL", symbol="AAPL"))
    assert len(drafts) == 1
    assert drafts[0].fact_kind == "sec_text.mdna"


def test_draft_carries_accession_and_filing_url() -> None:
    filings = [
        _FakeFiling(
            mdna="MD&A.",
            risk="Risks.",
            accession="0000320193-26-000001",
            url="https://sec.gov/Archives/edgar/data/320193/000032019326000001-index.htm",
        )
    ]
    source = EdgartoolsSource(company_resolver=_resolver(filings))
    drafts = _run(source.fetch_narrative_async(ticker_or_cik="AAPL", symbol="AAPL"))
    mdna = next(d for d in drafts if d.fact_kind == "sec_text.mdna")
    payload = mdna.value_jsonb
    assert isinstance(payload, dict)
    assert payload["accession_number"] == "0000320193-26-000001"
    assert payload["form"] == "10-K"
    assert payload["filing_date"] == "2026-03-15T00:00:00+00:00"
    assert payload["text_preview"].startswith("MD&A.")
    assert mdna.source_url.startswith("https://sec.gov/")
    # Dedupe key: per-section + per-accession.
    assert mdna.dedupe_key == "edgartools:sec_text.mdna:0000320193-26-000001"


def test_accession_number_filter() -> None:
    """Supplying ``accession_number`` scopes the lookup to a specific
    filing rather than the latest 10-K. Useful for backfilling an
    earlier filing whose MD&A changed materially."""
    target = "0000320193-25-000001"
    filings = [
        _FakeFiling(accession="0000320193-26-000001", mdna="new", risk="new"),
        _FakeFiling(accession=target, mdna="historical", risk="historical"),
    ]
    source = EdgartoolsSource(company_resolver=_resolver(filings))
    drafts = _run(
        source.fetch_narrative_async(ticker_or_cik="AAPL", symbol="AAPL", accession_number=target)
    )
    assert all(d.value_jsonb["accession_number"] == target for d in drafts)  # type: ignore[index]
    assert drafts[0].value_text == "historical"


# ---------------------------------------------------------------------------
# SourcePort legacy contract
# ---------------------------------------------------------------------------


def test_sourceport_fetch_returns_empty_iter() -> None:
    """The symbol-only legacy contract cannot carry accession scoping —
    callers must use ``fetch_narrative_async``."""
    source = EdgartoolsSource(company_resolver=_resolver([]))
    assert list(source.fetch("AAPL", None)) == []
