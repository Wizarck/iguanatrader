"""Unit tests for SEC EDGAR adapter (slice R2)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import httpx
import pytest
from iguanatrader.contexts.research.errors import ConfigError
from iguanatrader.contexts.research.sources.sec_edgar import SECEdgarSource


@pytest.fixture(autouse=True)
def _reset_class_state() -> Iterator[None]:
    SECEdgarSource._cik_cache = None
    yield
    SECEdgarSource._cik_cache = None


@pytest.fixture
def _ua_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "iguanatrader-test contact@example.com")


def test_init_requires_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEC_EDGAR_USER_AGENT", raising=False)
    with pytest.raises(ConfigError):
        SECEdgarSource()


def test_init_validates_user_agent_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "no-email-here")
    with pytest.raises(ConfigError):
        SECEdgarSource()


def test_init_accepts_well_formed_ua(_ua_env: None) -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={}))
    adapter = SECEdgarSource(client=httpx.Client(transport=transport))
    try:
        assert adapter._user_agent.startswith("iguanatrader-test ")
    finally:
        adapter.close()


_TICKERS_PAYLOAD = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
}

_SUBMISSIONS_PAYLOAD = {
    "filings": {
        "recent": {
            "accessionNumber": ["0000320193-24-000123", "0000320193-24-000099"],
            "form": ["10-K", "8-K"],
            "filingDate": ["2024-11-01", "2024-09-15"],
            "primaryDocument": ["aapl-20240928.htm", "aapl-8k.htm"],
            "periodOfReport": ["2024-09-28", "2024-09-15"],
        }
    }
}

_COMPANY_FACTS_PAYLOAD = {
    "facts": {
        "us-gaap": {
            "Revenues": {
                "units": {
                    "USD": [
                        {
                            "end": "2024-09-28",
                            "val": 391035000000,
                            "accn": "0000320193-24-000123",
                            "form": "10-K",
                            "fy": 2024,
                            "fp": "FY",
                        },
                        {
                            "end": "2023-09-30",
                            "val": 383285000000,
                            "accn": "0000320193-23-000106",
                            "form": "10-K",
                            "fy": 2023,
                            "fp": "FY",
                        },
                    ]
                }
            }
        }
    }
}


def _routing_handler(req: httpx.Request) -> httpx.Response:
    url = str(req.url)
    if "company_tickers" in url:
        return httpx.Response(200, json=_TICKERS_PAYLOAD)
    if "submissions/CIK" in url:
        return httpx.Response(200, json=_SUBMISSIONS_PAYLOAD)
    if "companyfacts/CIK" in url:
        return httpx.Response(200, json=_COMPANY_FACTS_PAYLOAD)
    return httpx.Response(404)


def test_fetch_emits_filing_drafts_with_filing_date_and_dedupe(_ua_env: None) -> None:
    transport = httpx.MockTransport(_routing_handler)
    adapter = SECEdgarSource(client=httpx.Client(transport=transport))
    try:
        drafts = list(adapter.fetch("AAPL", since=None))
    finally:
        adapter.close()
    filing_drafts = [d for d in drafts if d.fact_kind.startswith("sec_filing.")]
    assert len(filing_drafts) == 2
    ten_k = next(d for d in filing_drafts if d.fact_kind == "sec_filing.10-K")
    assert ten_k.effective_from == datetime(2024, 11, 1, tzinfo=UTC)
    assert ten_k.dedupe_key == "sec_edgar:0000320193-24-000123"
    assert ten_k.source_id == "sec_edgar"


def test_fetch_emits_xbrl_drafts_for_10k_only(_ua_env: None) -> None:
    transport = httpx.MockTransport(_routing_handler)
    adapter = SECEdgarSource(client=httpx.Client(transport=transport))
    try:
        drafts = list(adapter.fetch("AAPL", since=None))
    finally:
        adapter.close()
    xbrl_drafts = [d for d in drafts if d.fact_kind.startswith("sec_xbrl.")]
    assert len(xbrl_drafts) == 2  # both Revenues observations are form=10-K
    sample = xbrl_drafts[0]
    assert sample.value_numeric is not None
    assert sample.unit == "USD"
    assert sample.dedupe_key is not None
    assert sample.dedupe_key.startswith("sec_edgar:xbrl:320193:Revenues:")


def test_fetch_skips_unknown_ticker(_ua_env: None, caplog: pytest.LogCaptureFixture) -> None:
    transport = httpx.MockTransport(_routing_handler)
    adapter = SECEdgarSource(client=httpx.Client(transport=transport))
    try:
        drafts = list(adapter.fetch("UNKNOWNTICKER", since=None))
    finally:
        adapter.close()
    assert drafts == []


def test_fetch_filters_by_since(_ua_env: None) -> None:
    transport = httpx.MockTransport(_routing_handler)
    adapter = SECEdgarSource(client=httpx.Client(transport=transport))
    try:
        drafts = list(adapter.fetch("AAPL", since=datetime(2024, 10, 1, tzinfo=UTC)))
    finally:
        adapter.close()
    filing_drafts = [d for d in drafts if d.fact_kind.startswith("sec_filing.")]
    # Only the 2024-11-01 10-K is newer than 2024-10-01.
    assert len(filing_drafts) == 1
    assert filing_drafts[0].fact_kind == "sec_filing.10-K"


def test_fetch_dedupe_keys_are_unique(_ua_env: None) -> None:
    transport = httpx.MockTransport(_routing_handler)
    adapter = SECEdgarSource(client=httpx.Client(transport=transport))
    try:
        drafts = list(adapter.fetch("AAPL", since=None))
    finally:
        adapter.close()
    keys = [d.dedupe_key for d in drafts if d.dedupe_key]
    assert len(keys) == len(set(keys))
