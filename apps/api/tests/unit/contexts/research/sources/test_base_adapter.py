"""Unit tests for ``TierASourceAdapter`` (slice R2 base)."""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import patch

import httpx
import pytest
from iguanatrader.contexts.research.errors import ConfigError, SourceUnavailableError
from iguanatrader.contexts.research.sources.base import TierASourceAdapter


class _DummySource(TierASourceAdapter):
    SOURCE_ID: ClassVar[str] = "dummy"
    RATE_LIMIT_PER_SECOND: ClassVar[float] = 1000.0  # effectively no throttling


def _client_for(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def test_missing_source_id_raises_config_error() -> None:
    class _Bare(TierASourceAdapter):
        pass

    with pytest.raises(ConfigError):
        _Bare()


def test_request_json_returns_parsed_body_on_2xx() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"hello": "world"}))
    adapter = _DummySource(client=_client_for(transport))
    try:
        result = adapter._request_json("GET", "https://example.test/")
        assert result == {"hello": "world"}
    finally:
        adapter.close()


def test_request_json_returns_none_on_permanent_4xx() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(404))
    adapter = _DummySource(client=_client_for(transport))
    try:
        assert adapter._request_json("GET", "https://example.test/") is None
    finally:
        adapter.close()


def test_request_json_raises_after_exhausted_5xx() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(503))
    adapter = _DummySource(client=_client_for(transport))
    try:
        with patch("time.sleep"), pytest.raises(SourceUnavailableError):
            adapter._request_json("GET", "https://example.test/")
    finally:
        adapter.close()


def test_request_json_eventual_success_after_5xx() -> None:
    counter = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        if counter["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    adapter = _DummySource(client=_client_for(httpx.MockTransport(handler)))
    try:
        with patch("time.sleep"):
            result = adapter._request_json("GET", "https://example.test/")
        assert result == {"ok": True}
        assert counter["n"] == 3
    finally:
        adapter.close()


def test_request_json_honours_retry_after_on_429() -> None:
    counter = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        if counter["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0.0"})
        return httpx.Response(200, json={"ok": True})

    adapter = _DummySource(client=_client_for(httpx.MockTransport(handler)))
    try:
        with patch("time.sleep"):
            assert adapter._request_json("GET", "https://example.test/") == {"ok": True}
    finally:
        adapter.close()


def test_make_draft_sets_tier_a_defaults() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={}))
    adapter = _DummySource(client=_client_for(transport))
    try:
        from datetime import UTC, datetime

        draft = adapter._make_draft(
            fact_kind="dummy.kind",
            effective_from=datetime(2026, 1, 1, tzinfo=UTC),
            source_url="https://example.test/x",
            value_text="ok",
        )
        assert draft.source_id == "dummy"
        assert draft.retrieval_method == "api"
        assert draft.fact_kind == "dummy.kind"
        assert draft.dedupe_key is None
    finally:
        adapter.close()
