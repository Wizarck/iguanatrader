"""Unit tests for FinnhubSource (slice R3)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from iguanatrader.contexts.research.errors import ConfigError
from iguanatrader.contexts.research.sources.finnhub import FinnhubSource


def test_init_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        FinnhubSource()


@pytest.fixture
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")


_NEWS_PAYLOAD = [
    {
        "id": 12345,
        "datetime": 1700000000,
        "headline": "AAPL announces buyback",
        "summary": "Apple announces $90B share buyback program.",
        "source": "Reuters",
        "url": "https://example.com/aapl-buyback",
        "category": "company news",
        "related": "AAPL",
    },
    {
        "id": 12346,
        "datetime": 1700100000,
        "headline": "AAPL Q4 earnings beat estimates",
        "summary": "Apple Q4 EPS $1.46 vs $1.39 estimate.",
        "source": "CNBC",
        "url": "https://example.com/aapl-earnings",
        "category": "company news",
        "related": "AAPL",
    },
]


def test_fetch_emits_news_drafts(_api_key: None) -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=_NEWS_PAYLOAD))
    adapter = FinnhubSource(client=httpx.Client(transport=transport))
    try:
        drafts = list(adapter.fetch("AAPL", since=None))
    finally:
        adapter.close()
    assert len(drafts) == 2
    assert drafts[0].source_id == "finnhub"
    assert drafts[0].fact_kind == "finnhub.company_news"
    assert drafts[0].dedupe_key == "finnhub:news:12345"
    assert drafts[0].effective_from == datetime.fromtimestamp(1700000000, tz=UTC)


def test_fetch_skips_malformed_entries(_api_key: None) -> None:
    payload: list[dict[str, object]] = [
        {"id": 1, "datetime": 1700000000, "headline": "ok", "url": "https://x.test/a"},
        {"headline": "no id no time"},  # malformed → skipped
        {"id": 2, "datetime": 0, "headline": "zero time"},  # zero time → skipped
    ]
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    adapter = FinnhubSource(client=httpx.Client(transport=transport))
    try:
        drafts = list(adapter.fetch("AAPL", since=None))
    finally:
        adapter.close()
    assert len(drafts) == 1


def test_fetch_earnings_calendar_emits_drafts(_api_key: None) -> None:
    payload = {
        "earningsCalendar": [
            {
                "date": "2024-04-30",
                "epsEstimate": 1.39,
                "epsActual": 1.46,
                "revenueEstimate": 90000000000,
                "revenueActual": 91000000000,
                "hour": "amc",
                "year": 2024,
                "quarter": 2,
            }
        ]
    }
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    adapter = FinnhubSource(client=httpx.Client(transport=transport))
    try:
        drafts = list(adapter.fetch_earnings_calendar("AAPL"))
    finally:
        adapter.close()
    assert len(drafts) == 1
    assert drafts[0].fact_kind == "finnhub.earnings_calendar"
    assert drafts[0].dedupe_key == "finnhub:earnings:AAPL:2024-04-30"
