"""Unit tests for FRED adapter (slice R2)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from iguanatrader.contexts.research.errors import ConfigError
from iguanatrader.contexts.research.sources.fred import FREDSource


def test_init_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        FREDSource()


@pytest.fixture
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRED_API_KEY", "test-key")


_OBSERVATIONS = {
    "observations": [
        {
            "date": "2024-01-01",
            "value": "3.4",
            "realtime_start": "2024-02-13",
            "realtime_end": "9999-12-31",
        },
        {
            "date": "2024-02-01",
            "value": "3.2",
            "realtime_start": "2024-03-12",
            "realtime_end": "9999-12-31",
        },
        {
            "date": "2024-03-01",
            "value": ".",  # FRED missing-data sentinel
            "realtime_start": "2024-04-10",
            "realtime_end": "9999-12-31",
        },
    ]
}


def test_fetch_series_emits_drafts_with_alfred_vintage(_api_key: None) -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=_OBSERVATIONS))
    adapter = FREDSource(client=httpx.Client(transport=transport))
    try:
        drafts = list(adapter.fetch_series("CPIAUCSL"))
    finally:
        adapter.close()
    assert len(drafts) == 2  # missing observation is skipped
    first = drafts[0]
    assert first.source_id == "fred"
    assert first.fact_kind == "fred.CPIAUCSL"
    assert first.effective_from == datetime(2024, 1, 1, tzinfo=UTC)
    assert first.recorded_from == datetime(2024, 2, 13, tzinfo=UTC)
    assert first.value_numeric == Decimal("3.4")
    assert first.dedupe_key == "fred:CPIAUCSL:2024-01-01:2024-02-13"


def test_fetch_series_skips_missing_dot_value(_api_key: None) -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=_OBSERVATIONS))
    adapter = FREDSource(client=httpx.Client(transport=transport))
    try:
        drafts = list(adapter.fetch_series("CPIAUCSL"))
    finally:
        adapter.close()
    march_drafts = [d for d in drafts if d.effective_from == datetime(2024, 3, 1, tzinfo=UTC)]
    assert march_drafts == []


def test_fetch_series_filters_by_since(_api_key: None) -> None:
    captured: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["realtime_start"] = req.url.params.get("realtime_start") or ""
        return httpx.Response(200, json={"observations": []})

    transport = httpx.MockTransport(handler)
    adapter = FREDSource(client=httpx.Client(transport=transport))
    try:
        list(adapter.fetch_series("DGS10", since=datetime(2024, 6, 15, tzinfo=UTC)))
    finally:
        adapter.close()
    assert captured["realtime_start"] == "2024-06-15"


def test_fetch_series_handles_4xx_as_no_data(_api_key: None) -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(400))
    adapter = FREDSource(client=httpx.Client(transport=transport))
    try:
        drafts = list(adapter.fetch_series("BADID"))
    finally:
        adapter.close()
    assert drafts == []
