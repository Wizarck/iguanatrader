"""Unit tests for the IBKR research adapter (slice I3).

Pure-unit — no TWS, no DB, no ib_async. Tests inject a mock client
against the :class:`IBKRResearchClient` Protocol so the adapter's
sub-flow plumbing, fact_kind labels, and best-effort degradation can
all be exercised in isolation.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from iguanatrader.contexts.research.sources.ibkr import (
    DEFAULT_HISTORICAL_DURATION_DAYS,
    IBKRSource,
)


class _FakeClient:
    """Hand-rolled mock of :class:`IBKRResearchClient`.

    Each method's return is set via the constructor; setting it to an
    Exception triggers the failure branch instead.
    """

    def __init__(
        self,
        *,
        snapshot: Any = None,
        bars: Any = None,
        contract: Any = None,
    ) -> None:
        self._snapshot = snapshot
        self._bars = bars
        self._contract = contract
        self.connected = False
        self.disconnected = False
        self.calls: list[str] = []

    async def connect_async(self, host: str, port: int, client_id: int) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.disconnected = True

    async def market_snapshot(self, symbol: str) -> dict[str, Any]:
        self.calls.append(f"snapshot:{symbol}")
        if isinstance(self._snapshot, Exception):
            raise self._snapshot
        return self._snapshot or {}

    async def historical_bars(
        self, symbol: str, duration_str: str, bar_size: str
    ) -> list[dict[str, Any]]:
        self.calls.append(f"historical:{symbol}:{duration_str}:{bar_size}")
        if isinstance(self._bars, Exception):
            raise self._bars
        return list(self._bars or [])

    async def contract_details(self, symbol: str) -> dict[str, Any]:
        self.calls.append(f"contract:{symbol}")
        if isinstance(self._contract, Exception):
            raise self._contract
        return self._contract or {}


def _run(coro: Any) -> Any:
    # Each test invocation gets a fresh loop — keeps Python 3.13's
    # "no current event loop" deprecation from triggering and avoids
    # cross-test loop state leakage.
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Sub-flow inclusion
# ---------------------------------------------------------------------------


def test_fetch_async_all_subflows_default() -> None:
    client = _FakeClient(
        snapshot={"forward_pe": 32.7},
        bars=[
            {
                "date": "2026-05-15",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1000,
            }
        ],
        contract={"long_name": "Advanced Micro Devices", "industry": "Semis"},
    )
    source = IBKRSource(client=client)
    drafts = _run(source.fetch_async("AMD"))

    assert len(drafts) == 3
    kinds = {d.fact_kind for d in drafts}
    assert kinds == {"ibkr_snapshot", "historical_prices_window", "contract_details"}
    assert {d.source_id for d in drafts} == {"ibkr"}


def test_fetch_async_respects_include_subset() -> None:
    client = _FakeClient(snapshot={"forward_pe": 32.7})
    source = IBKRSource(client=client)
    drafts = _run(source.fetch_async("AMD", include=["snapshot"]))

    assert len(drafts) == 1
    assert drafts[0].fact_kind == "ibkr_snapshot"
    # Other sub-flows never invoked.
    assert all("historical" not in c and "contract" not in c for c in client.calls)


def test_fetch_async_unknown_subflow_raises() -> None:
    source = IBKRSource(client=_FakeClient())
    with pytest.raises(ValueError, match="Unknown ibkr sub-flow"):
        _run(source.fetch_async("AMD", include=["bogus"]))


def test_fetch_async_empty_include_falls_back_to_all() -> None:
    # Empty list (whitespace-only entries) → treat as "all" rather than
    # silently no-op so the operator gets the intended default.
    client = _FakeClient(snapshot={"forward_pe": 32.7}, bars=[], contract={})
    source = IBKRSource(client=client)
    drafts = _run(source.fetch_async("AMD", include=["", "  "]))
    assert len(drafts) == 1  # only the snapshot returned non-empty


# ---------------------------------------------------------------------------
# Best-effort degradation
# ---------------------------------------------------------------------------


def test_snapshot_failure_does_not_abort_other_subflows() -> None:
    client = _FakeClient(
        snapshot=RuntimeError("TWS timeout"),
        bars=[{"date": "2026-05-15", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}],
        contract={"long_name": "X"},
    )
    source = IBKRSource(client=client)
    drafts = _run(source.fetch_async("X"))

    kinds = {d.fact_kind for d in drafts}
    # Snapshot dropped silently; historical + contract still ship.
    assert "ibkr_snapshot" not in kinds
    assert kinds == {"historical_prices_window", "contract_details"}


def test_historical_failure_does_not_abort_other_subflows() -> None:
    client = _FakeClient(
        snapshot={"forward_pe": 30.0},
        bars=RuntimeError("hmds query returned no data"),
        contract={"long_name": "X"},
    )
    source = IBKRSource(client=client)
    drafts = _run(source.fetch_async("X"))

    kinds = {d.fact_kind for d in drafts}
    assert "historical_prices_window" not in kinds
    assert kinds == {"ibkr_snapshot", "contract_details"}


def test_contract_failure_does_not_abort_other_subflows() -> None:
    client = _FakeClient(
        snapshot={"forward_pe": 30.0},
        bars=[{"date": "2026-05-15", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}],
        contract=ValueError("ambiguous contract"),
    )
    source = IBKRSource(client=client)
    drafts = _run(source.fetch_async("X"))

    kinds = {d.fact_kind for d in drafts}
    assert "contract_details" not in kinds
    assert kinds == {"ibkr_snapshot", "historical_prices_window"}


def test_all_subflows_fail_returns_empty() -> None:
    client = _FakeClient(
        snapshot=RuntimeError("e1"),
        bars=RuntimeError("e2"),
        contract=RuntimeError("e3"),
    )
    source = IBKRSource(client=client)
    drafts = _run(source.fetch_async("X"))
    assert drafts == []


# ---------------------------------------------------------------------------
# Draft shape invariants
# ---------------------------------------------------------------------------


def test_snapshot_draft_carries_ratio_payload_and_dedupe_key() -> None:
    payload = {"forward_pe": 32.74, "beta": 1.85, "market_cap": 691.5e9}
    client = _FakeClient(snapshot=payload)
    source = IBKRSource(client=client)
    [draft] = _run(source.fetch_async("AMD", include=["snapshot"]))

    assert draft.value_jsonb == payload
    assert draft.dedupe_key is not None
    assert draft.dedupe_key.startswith("ibkr:snapshot:AMD:")
    assert draft.source_url == "ibkr://snapshot/AMD"
    assert draft.retrieval_method == "api"


def test_historical_draft_window_metadata() -> None:
    bars = [
        {
            "date": "2026-04-01",
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "volume": 5000,
        },
        {
            "date": "2026-05-15",
            "open": 110.0,
            "high": 112.0,
            "low": 109.0,
            "close": 111.0,
            "volume": 6000,
        },
    ]
    client = _FakeClient(bars=bars)
    source = IBKRSource(client=client)
    [draft] = _run(source.fetch_async("AMD", include=["historical"]))

    assert draft.fact_kind == "historical_prices_window"
    assert draft.value_jsonb is not None
    assert draft.value_jsonb["symbol"] == "AMD"
    assert draft.value_jsonb["bars"] == bars
    assert draft.value_jsonb["bar_size"] == "1 day"
    # effective_from = first bar date (window start), preserving the
    # bitemporal contract for downstream as-of queries.
    assert draft.effective_from.date().isoformat() == "2026-04-01"
    # The CLI passes ``f"{N} D"`` to the client — assert that contract.
    call_str = client.calls[0]
    assert f"{DEFAULT_HISTORICAL_DURATION_DAYS} D" in call_str


def test_contract_details_draft_shape() -> None:
    payload = {
        "long_name": "Advanced Micro Devices",
        "industry": "Semiconductors",
        "category": "Computer Hardware",
        "primary_exchange": "NASDAQ",
        "currency": "USD",
    }
    client = _FakeClient(contract=payload)
    source = IBKRSource(client=client)
    [draft] = _run(source.fetch_async("AMD", include=["contract"]))

    assert draft.fact_kind == "contract_details"
    assert draft.value_jsonb == payload
    assert draft.dedupe_key == "ibkr:contract:AMD"


# ---------------------------------------------------------------------------
# Disable flag
# ---------------------------------------------------------------------------


def test_fetch_async_skipped_when_disabled() -> None:
    client = _FakeClient(snapshot={"forward_pe": 32.7})
    source = IBKRSource(client=client, enabled=False)
    drafts = _run(source.fetch_async("AMD"))
    assert drafts == []
    # Client never invoked.
    assert client.calls == []


# ---------------------------------------------------------------------------
# Empty-result handling
# ---------------------------------------------------------------------------


def test_empty_snapshot_yields_no_draft() -> None:
    client = _FakeClient(snapshot={})
    source = IBKRSource(client=client)
    drafts = _run(source.fetch_async("AMD", include=["snapshot"]))
    assert drafts == []


def test_empty_bars_yields_no_draft() -> None:
    client = _FakeClient(bars=[])
    source = IBKRSource(client=client)
    drafts = _run(source.fetch_async("AMD", include=["historical"]))
    assert drafts == []


def test_empty_contract_yields_no_draft() -> None:
    client = _FakeClient(contract={})
    source = IBKRSource(client=client)
    drafts = _run(source.fetch_async("AMD", include=["contract"]))
    assert drafts == []
