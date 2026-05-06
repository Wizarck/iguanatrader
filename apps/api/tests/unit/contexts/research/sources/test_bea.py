"""Unit tests for BEA adapter (slice R2)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from iguanatrader.contexts.research.errors import ConfigError
from iguanatrader.contexts.research.sources.bea import BEASource


def test_init_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BEA_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        BEASource()


@pytest.fixture
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BEA_API_KEY", "test-key")


_NIPA_PAYLOAD = {
    "BEAAPI": {
        "Results": {
            "Data": [
                {
                    "TimePeriod": "2024Q1",
                    "DataValue": "23,456.7",
                    "LineNumber": "1",
                    "LineDescription": "Gross domestic product",
                    "SeriesCode": "A191RC",
                    "CL_UNIT": "Level",
                    "NoteRef": "T10101",
                },
                {
                    "TimePeriod": "2024Q2",
                    "DataValue": "...",  # ellipsis = missing
                    "LineNumber": "1",
                    "LineDescription": "Gross domestic product",
                    "SeriesCode": "A191RC",
                    "CL_UNIT": "Level",
                    "NoteRef": "T10101",
                },
                {
                    "TimePeriod": "2024",
                    "DataValue": "27,357.0",
                    "LineNumber": "1",
                    "LineDescription": "Gross domestic product",
                    "SeriesCode": "A191RC",
                    "CL_UNIT": "Level",
                    "NoteRef": "T10101",
                },
            ]
        }
    }
}


def test_fetch_dataset_emits_quarterly_drafts(_api_key: None) -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=_NIPA_PAYLOAD))
    adapter = BEASource(client=httpx.Client(transport=transport))
    try:
        drafts = list(adapter.fetch_dataset("NIPA", "T10101", "Q"))
    finally:
        adapter.close()
    # Ellipsis row skipped → 2 valid rows.
    assert len(drafts) == 2
    q1 = drafts[0]
    assert q1.effective_from == datetime(2024, 1, 1, tzinfo=UTC)
    assert q1.effective_to == datetime(2024, 3, 31, 23, 59, 59, tzinfo=UTC)
    assert q1.value_numeric == Decimal("23456.7")
    assert q1.unit == "Level"
    assert q1.dedupe_key is not None
    assert q1.dedupe_key.startswith("bea:NIPA:T10101:Q:2024Q1:")


def test_fetch_dataset_handles_annual_period(_api_key: None) -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=_NIPA_PAYLOAD))
    adapter = BEASource(client=httpx.Client(transport=transport))
    try:
        drafts = list(adapter.fetch_dataset("NIPA", "T10101", "A"))
    finally:
        adapter.close()
    annuals = [
        d
        for d in drafts
        if d.fact_metadata is not None and d.fact_metadata.get("time_period") == "2024"
    ]
    assert len(annuals) == 1
    assert annuals[0].effective_from == datetime(2024, 1, 1, tzinfo=UTC)
    assert annuals[0].effective_to == datetime(2024, 12, 31, 23, 59, 59, tzinfo=UTC)
    assert annuals[0].value_numeric == Decimal("27357.0")


def test_fetch_dataset_strips_thousands_commas(_api_key: None) -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=_NIPA_PAYLOAD))
    adapter = BEASource(client=httpx.Client(transport=transport))
    try:
        drafts = list(adapter.fetch_dataset("NIPA", "T10101", "Q"))
    finally:
        adapter.close()
    assert all(isinstance(d.value_numeric, Decimal) for d in drafts)
    assert all(d.value_numeric > 0 for d in drafts if d.value_numeric is not None)


def test_fetch_dataset_skips_unparseable_period(_api_key: None) -> None:
    payload = {
        "BEAAPI": {
            "Results": {
                "Data": [
                    {
                        "TimePeriod": "WEIRDFORMAT",
                        "DataValue": "100",
                        "LineNumber": "1",
                        "LineDescription": "X",
                    },
                ]
            }
        }
    }
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    adapter = BEASource(client=httpx.Client(transport=transport))
    try:
        drafts = list(adapter.fetch_dataset("NIPA", "T10101", "Q"))
    finally:
        adapter.close()
    assert drafts == []
