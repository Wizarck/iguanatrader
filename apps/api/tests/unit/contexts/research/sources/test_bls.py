"""Unit tests for BLS adapter (slice R2)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from iguanatrader.contexts.research.errors import ConfigError, RateLimitedError
from iguanatrader.contexts.research.sources.bls import BLSSource


def test_init_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BLS_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        BLSSource()


@pytest.fixture
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLS_API_KEY", "test-key")


_SUCCESS_PAYLOAD = {
    "status": "REQUEST_SUCCEEDED",
    "Results": {
        "series": [
            {
                "seriesID": "LNS14000000",
                "data": [
                    {"year": "2024", "period": "M01", "value": "3.7"},
                    {"year": "2024", "period": "M02", "value": "3.9"},
                    {"year": "2024", "period": "Q01", "value": "3.8"},
                ],
            }
        ]
    },
}


def test_fetch_series_emits_monthly_drafts(_api_key: None) -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=_SUCCESS_PAYLOAD))
    adapter = BLSSource(client=httpx.Client(transport=transport))
    try:
        drafts = list(adapter.fetch_series("LNS14000000"))
    finally:
        adapter.close()
    monthly = [
        d
        for d in drafts
        if d.fact_metadata and str(d.fact_metadata.get("period", "")).startswith("M")
    ]
    assert len(monthly) == 2
    jan = next(d for d in monthly if d.fact_metadata and d.fact_metadata["period"] == "M01")
    assert jan.effective_from == datetime(2024, 1, 1, tzinfo=UTC)
    assert jan.effective_to == datetime(2024, 1, 31, 23, 59, 59, tzinfo=UTC)
    assert jan.value_numeric == Decimal("3.7")
    assert jan.dedupe_key is not None
    assert jan.dedupe_key.startswith("bls:LNS14000000:2024:M01:")


def test_fetch_series_emits_quarterly_drafts(_api_key: None) -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=_SUCCESS_PAYLOAD))
    adapter = BLSSource(client=httpx.Client(transport=transport))
    try:
        drafts = list(adapter.fetch_series("LNS14000000"))
    finally:
        adapter.close()
    quarterly = [d for d in drafts if d.fact_metadata and d.fact_metadata.get("period") == "Q01"]
    assert len(quarterly) == 1
    q1 = quarterly[0]
    assert q1.effective_from == datetime(2024, 1, 1, tzinfo=UTC)
    assert q1.effective_to == datetime(2024, 3, 31, 23, 59, 59, tzinfo=UTC)


def test_fetch_series_raises_on_request_not_processed(_api_key: None) -> None:
    payload = {
        "status": "REQUEST_NOT_PROCESSED",
        "message": ["Threshold reached"],
        "Results": {},
    }
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    adapter = BLSSource(client=httpx.Client(transport=transport))
    try:
        with pytest.raises(RateLimitedError):
            list(adapter.fetch_series("LNS14000000"))
    finally:
        adapter.close()


def test_fetch_series_skips_unsupported_periods(_api_key: None) -> None:
    payload = {
        "status": "REQUEST_SUCCEEDED",
        "Results": {
            "series": [
                {
                    "seriesID": "TEST",
                    "data": [
                        {"year": "2024", "period": "S01", "value": "1.0"},  # semi-annual
                        {"year": "2024", "period": "M01", "value": "1.0"},
                    ],
                }
            ]
        },
    }
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    adapter = BLSSource(client=httpx.Client(transport=transport))
    try:
        drafts = list(adapter.fetch_series("TEST"))
    finally:
        adapter.close()
    assert len(drafts) == 1
    assert drafts[0].fact_metadata is not None
    assert drafts[0].fact_metadata["period"] == "M01"
