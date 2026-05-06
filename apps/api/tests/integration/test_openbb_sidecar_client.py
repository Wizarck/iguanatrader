"""Integration tests for the OpenBBSidecarSource adapter.

These tests run against a *mock* sidecar (canned httpx responses) — no
network. The matching live-sidecar test lives in
``test_openbb_sidecar_e2e.py`` under the ``sidecar_live`` pytest marker
which CI runs in a separate job after `docker compose up -d openbb_sidecar`.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from iguanatrader.contexts.research.ports import ResearchFactDraft
from iguanatrader.contexts.research.sources.openbb_sidecar import (
    MAX_RETRY_ATTEMPTS,
    OpenBBSidecarSource,
)
from iguanatrader.shared.errors import IntegrationError


def _canned_payload(endpoint: str, symbol: str) -> dict[str, Any]:
    if endpoint == "fundamentals":
        return {
            "symbol": symbol,
            "pe_ratio": 22.5,
            "market_cap": 3_500_000_000_000.0,
            "dividend_yield": 0.005,
            "as_of_date": "2026-04-30T00:00:00",
        }
    if endpoint == "ratings":
        return {
            "symbol": symbol,
            "consensus": "Buy",
            "target_price": 250.0,
            "analyst_count": 42,
            "as_of_date": "2026-04-29T00:00:00",
        }
    if endpoint == "esg":
        return {
            "symbol": symbol,
            "esg_score": 65.0,
            "environmental_score": 60.0,
            "social_score": 70.0,
            "governance_score": 65.0,
            "as_of_date": "2026-03-31T00:00:00",
        }
    raise ValueError(f"unknown endpoint {endpoint}")


def _make_mock_transport(
    responses: dict[str, tuple[int, dict[str, Any] | None]],
) -> httpx.MockTransport:
    """Build an httpx MockTransport keyed on the URL path's last segment."""

    def handler(request: httpx.Request) -> httpx.Response:
        # path is /v1/equity/<endpoint>/<symbol> — pull the endpoint slug
        parts = request.url.path.strip("/").split("/")
        endpoint = parts[-2]  # fundamentals|ratings|esg
        if endpoint not in responses:
            return httpx.Response(404)
        status, body = responses[endpoint]
        if body is None:
            return httpx.Response(status)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


@pytest.fixture
def no_sleep() -> Iterable[None]:
    """Skip the backoff sleep so retry tests run in milliseconds."""
    with patch("time.sleep"):
        yield


def test_fetch_yields_three_drafts_on_happy_path() -> None:
    transport = _make_mock_transport(
        {
            "fundamentals": (200, _canned_payload("fundamentals", "AAPL")),
            "ratings": (200, _canned_payload("ratings", "AAPL")),
            "esg": (200, _canned_payload("esg", "AAPL")),
        }
    )
    client = httpx.Client(transport=transport)
    source = OpenBBSidecarSource(base_url="http://test", client=client)

    drafts = list(source.fetch("AAPL", since=None))
    assert len(drafts) == 3
    fact_kinds = sorted(d.fact_kind for d in drafts)
    assert fact_kinds == ["analyst_ratings", "esg_score", "fundamentals"]
    for d in drafts:
        assert isinstance(d, ResearchFactDraft)
        assert d.source_id == "openbb-sidecar"
        assert d.value_jsonb is not None
        assert d.value_jsonb["symbol"] == "AAPL"


def test_fetch_skips_endpoint_on_404_no_data() -> None:
    transport = _make_mock_transport(
        {
            "fundamentals": (200, _canned_payload("fundamentals", "AAPL")),
            "ratings": (404, None),
            "esg": (200, _canned_payload("esg", "AAPL")),
        }
    )
    client = httpx.Client(transport=transport)
    source = OpenBBSidecarSource(base_url="http://test", client=client)

    drafts = list(source.fetch("AAPL", since=None))
    # Only fundamentals + esg yield drafts; 404 ratings is skipped silently.
    assert len(drafts) == 2
    assert {d.fact_kind for d in drafts} == {"fundamentals", "esg_score"}


def test_fetch_retries_on_5xx_then_raises_after_exhaustion(no_sleep: None) -> None:
    call_count = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["count"] += 1
        return httpx.Response(503)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    source = OpenBBSidecarSource(base_url="http://test", client=client)

    with pytest.raises(IntegrationError) as exc:
        list(source.fetch("AAPL", since=None))
    assert "unreachable" in str(exc.value).lower() or "503" in str(exc.value)
    # First endpoint exhausts MAX_RETRY_ATTEMPTS attempts then raises;
    # later endpoints are not attempted because the iterator raises.
    assert call_count["count"] == MAX_RETRY_ATTEMPTS


def test_fetch_retries_on_transport_error_then_raises(no_sleep: None) -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        raise httpx.ConnectError("simulated connection refused")

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    source = OpenBBSidecarSource(base_url="http://test", client=client)

    with pytest.raises(IntegrationError):
        list(source.fetch("AAPL", since=None))
    assert attempts["count"] == MAX_RETRY_ATTEMPTS


def test_fetch_yields_nothing_when_disabled() -> None:
    # Construct disabled source even with a working transport — yields zero.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_canned_payload("fundamentals", "AAPL"))

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    source = OpenBBSidecarSource(base_url="http://test", client=client, enabled=False)

    drafts = list(source.fetch("AAPL", since=None))
    assert drafts == []


def test_fetch_disabled_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENBB_SIDECAR_ENABLED", "false")
    # Use a transport that would FAIL if reached — assert it never is.
    handler_calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        handler_calls["count"] += 1
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    source = OpenBBSidecarSource(base_url="http://test", client=client)

    drafts = list(source.fetch("AAPL", since=None))
    assert drafts == []
    assert handler_calls["count"] == 0


def test_drafts_use_payload_bytes_for_hybrid_storage() -> None:
    transport = _make_mock_transport(
        {"fundamentals": (200, _canned_payload("fundamentals", "AAPL"))}
    )
    client = httpx.Client(transport=transport)
    source = OpenBBSidecarSource(base_url="http://test", client=client)

    drafts = list(source.fetch("AAPL", since=None))
    fund = next(d for d in drafts if d.fact_kind == "fundamentals")
    # `with_payload` populates raw_payload_inline (small payload) +
    # raw_payload_sha256 + raw_payload_size_bytes per R1's hybrid contract.
    assert fund.raw_payload_inline is not None or fund.raw_payload_path is not None
    assert fund.raw_payload_sha256 is not None
    assert fund.raw_payload_size_bytes is not None
    assert fund.raw_payload_size_bytes > 0


def test_yfinance_proxy_retags_drafts_with_yfinance_source_id() -> None:
    from iguanatrader.contexts.research.sources.yfinance_proxy import (
        YFinanceProxySource,
    )

    transport = _make_mock_transport(
        {"fundamentals": (200, _canned_payload("fundamentals", "AAPL"))}
    )
    client = httpx.Client(transport=transport)
    source = YFinanceProxySource(base_url="http://test", client=client)

    drafts = list(source.fetch("AAPL", since=None))
    assert all(d.source_id == "yfinance" for d in drafts)
    fund = next(d for d in drafts if d.fact_kind == "fundamentals")
    assert fund.fact_metadata is not None
    assert fund.fact_metadata.get("via") == "openbb-sidecar"
    assert fund.fact_metadata.get("underlying_provider") == "yfinance"
