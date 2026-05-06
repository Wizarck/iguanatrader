"""Unit tests for GDELTSource (slice R3)."""

from __future__ import annotations

import httpx
from iguanatrader.contexts.research.sources.gdelt import GDELTSource

_PAYLOAD = {
    "articles": [
        {
            "title": "AAPL launches new product",
            "url": "https://news.example.com/aapl-launch",
            "domain": "news.example.com",
            "language": "English",
            "tone": "1.5",
            "seendate": "20240115T143000Z",
        }
    ]
}


def test_fetch_emits_article_drafts() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=_PAYLOAD))
    adapter = GDELTSource(client=httpx.Client(transport=transport))
    try:
        drafts = list(adapter.fetch("AAPL", since=None))
    finally:
        adapter.close()
    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.source_id == "gdelt"
    assert draft.fact_kind == "gdelt.article"
    assert draft.dedupe_key is not None
    assert draft.dedupe_key.startswith("gdelt:")
    assert "AAPL launches" in (draft.value_text or "")


def test_fetch_skips_malformed_seendate() -> None:
    payload = {
        "articles": [
            {"title": "ok", "url": "https://x.test/", "seendate": "BAD"},
        ]
    }
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    adapter = GDELTSource(client=httpx.Client(transport=transport))
    try:
        drafts = list(adapter.fetch("AAPL", since=None))
    finally:
        adapter.close()
    assert drafts == []
