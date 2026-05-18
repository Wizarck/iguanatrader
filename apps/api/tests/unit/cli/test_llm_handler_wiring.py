"""Unit tests for the composition-root LLM-handler wiring.

Pure-unit — no Anthropic client, no DB, no scheduler. Fakes inject
the per-Protocol contracts so the wiring's bus subscriptions +
adapter shape can be validated in isolation.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from iguanatrader.cli.llm_handler_wiring import (
    TradeJournalPersistAdapter,
    TradeProposalLoaderAdapter,
    build_explainer_narrative_provider,
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# TradeJournalPersistAdapter
# ---------------------------------------------------------------------------


@dataclass
class _FakeTrade:
    id: UUID
    symbol: str = "NVDA"
    side: str = "buy"
    quantity: Decimal = Decimal("100")
    mode: str = "paper"
    opened_at: datetime = field(default_factory=lambda: datetime(2026, 5, 1, 14, 0, tzinfo=UTC))
    closed_at: datetime | None = field(
        default_factory=lambda: datetime(2026, 5, 3, 16, 30, tzinfo=UTC)
    )
    exit_reason: str | None = "target"
    realised_pnl: Decimal | None = Decimal("125.50")
    journal_narrative: str | None = None
    journal_generated_at: datetime | None = None
    journal_model: str | None = None


class _FakeTradeRepo:
    def __init__(self, *, trades: dict[UUID, _FakeTrade]) -> None:
        self._trades = trades

    async def get_by_id(self, trade_id: UUID) -> _FakeTrade | None:
        return self._trades.get(trade_id)


@dataclass
class _FakeJournalResult:
    narrative: str
    model: str = "claude-haiku-4-5"


class _FakeJournalWriter:
    def __init__(self, *, narrative: str = "post-mortem text") -> None:
        self._narrative = narrative
        self.calls: list[dict[str, Any]] = []

    async def write(self, **kwargs: Any) -> _FakeJournalResult:
        self.calls.append(kwargs)
        return _FakeJournalResult(narrative=self._narrative)


def test_journal_adapter_writes_and_persists_narrative() -> None:
    trade = _FakeTrade(id=uuid4())
    repo = _FakeTradeRepo(trades={trade.id: trade})
    writer = _FakeJournalWriter(narrative="AMD broke entry levels...")
    adapter = TradeJournalPersistAdapter(
        writer=writer,  # type: ignore[arg-type]
        trade_repo=repo,  # type: ignore[arg-type]
    )

    result = _run(adapter.write_and_persist(trade_id=trade.id))

    assert result == "AMD broke entry levels..."
    assert trade.journal_narrative == "AMD broke entry levels..."
    assert trade.journal_model == "claude-haiku-4-5"
    assert trade.journal_generated_at is not None


def test_journal_adapter_is_idempotent_when_narrative_cached() -> None:
    """If the trade row already has a narrative (manual /journal route
    or a prior auto-journal pass), the writer is NOT invoked again."""
    trade = _FakeTrade(id=uuid4(), journal_narrative="already on row")
    repo = _FakeTradeRepo(trades={trade.id: trade})
    writer = _FakeJournalWriter()
    adapter = TradeJournalPersistAdapter(
        writer=writer,  # type: ignore[arg-type]
        trade_repo=repo,  # type: ignore[arg-type]
    )

    result = _run(adapter.write_and_persist(trade_id=trade.id))

    assert result == "already on row"
    assert writer.calls == []  # no LLM call


def test_journal_adapter_raises_when_trade_missing() -> None:
    repo = _FakeTradeRepo(trades={})
    writer = _FakeJournalWriter()
    adapter = TradeJournalPersistAdapter(
        writer=writer,  # type: ignore[arg-type]
        trade_repo=repo,  # type: ignore[arg-type]
    )

    with pytest.raises(LookupError, match="not found"):
        _run(adapter.write_and_persist(trade_id=uuid4()))


# ---------------------------------------------------------------------------
# TradeProposalLoaderAdapter
# ---------------------------------------------------------------------------


@dataclass
class _FakeProposal:
    id: UUID
    symbol: str = "NVDA"
    side: str = "buy"
    quantity: Decimal = Decimal("100")
    entry_price_indicative: Decimal = Decimal("165.00")
    stop_price: Decimal = Decimal("158.00")
    confidence_score: Decimal | None = Decimal("0.85")
    mode: str = "paper"
    reasoning: dict[str, Any] = field(default_factory=dict)


class _FakeProposalRepo:
    def __init__(self, *, proposals: dict[UUID, _FakeProposal]) -> None:
        self._proposals = proposals

    async def get_by_id(self, proposal_id: UUID) -> _FakeProposal | None:
        return self._proposals.get(proposal_id)


def test_proposal_loader_returns_row_on_hit() -> None:
    prop = _FakeProposal(id=uuid4())
    repo = _FakeProposalRepo(proposals={prop.id: prop})
    loader = TradeProposalLoaderAdapter(
        proposal_repo=repo,  # type: ignore[arg-type]
    )

    result = _run(loader.load(prop.id))
    assert result is prop


def test_proposal_loader_accepts_str_uuid() -> None:
    """The handler passes ``event.proposal_id`` straight through; if the
    bus serialised the event the field may surface as a string."""
    prop = _FakeProposal(id=uuid4())
    repo = _FakeProposalRepo(proposals={prop.id: prop})
    loader = TradeProposalLoaderAdapter(
        proposal_repo=repo,  # type: ignore[arg-type]
    )

    result = _run(loader.load(str(prop.id)))
    assert result is prop


def test_proposal_loader_raises_on_miss() -> None:
    repo = _FakeProposalRepo(proposals={})
    loader = TradeProposalLoaderAdapter(
        proposal_repo=repo,  # type: ignore[arg-type]
    )

    with pytest.raises(LookupError, match="not found"):
        _run(loader.load(uuid4()))


# ---------------------------------------------------------------------------
# build_explainer_narrative_provider
# ---------------------------------------------------------------------------


@dataclass
class _FakeApprovalRequest:
    id: UUID
    proposal_id: UUID


@dataclass
class _FakeExplainerResult:
    narrative: str


class _FakeExplainer:
    def __init__(self, *, narrative: str = "explanation text") -> None:
        self._narrative = narrative
        self.calls: list[dict[str, Any]] = []

    async def explain(self, **kwargs: Any) -> _FakeExplainerResult:
        self.calls.append(kwargs)
        return _FakeExplainerResult(narrative=self._narrative)


def test_narrative_provider_loads_proposal_and_returns_explanation() -> None:
    prop = _FakeProposal(id=uuid4())
    repo = _FakeProposalRepo(proposals={prop.id: prop})
    explainer = _FakeExplainer(narrative="entry at 165, stop at 158")
    provider = build_explainer_narrative_provider(
        explainer=explainer,  # type: ignore[arg-type]
        proposal_repo=repo,  # type: ignore[arg-type]
    )
    request = _FakeApprovalRequest(id=uuid4(), proposal_id=prop.id)

    narrative = _run(provider(request))  # type: ignore[arg-type]

    assert narrative == "entry at 165, stop at 158"
    assert len(explainer.calls) == 1
    assert explainer.calls[0]["symbol"] == "NVDA"
    assert explainer.calls[0]["proposal_id"] == str(prop.id)


def test_narrative_provider_returns_empty_when_proposal_missing() -> None:
    """A missing proposal is treated as "no narrative" — the inner
    dispatcher then falls back to its raw template (A1 wrapper skips
    attachment on empty strings)."""
    repo = _FakeProposalRepo(proposals={})
    explainer = _FakeExplainer()
    provider = build_explainer_narrative_provider(
        explainer=explainer,  # type: ignore[arg-type]
        proposal_repo=repo,  # type: ignore[arg-type]
    )
    request = _FakeApprovalRequest(id=uuid4(), proposal_id=uuid4())

    narrative = _run(provider(request))  # type: ignore[arg-type]
    assert narrative == ""
    assert explainer.calls == []


def test_narrative_provider_swallows_repo_failure() -> None:
    """A repo lookup that raises must NOT propagate — the wrapper's
    best-effort contract requires the inner dispatcher to still fan
    out (with an empty narrative)."""

    class _FailingRepo:
        async def get_by_id(self, _pid: UUID) -> None:
            raise RuntimeError("session dropped")

    explainer = _FakeExplainer()
    provider = build_explainer_narrative_provider(
        explainer=explainer,  # type: ignore[arg-type]
        proposal_repo=_FailingRepo(),  # type: ignore[arg-type]
    )
    request = _FakeApprovalRequest(id=uuid4(), proposal_id=uuid4())

    narrative = _run(provider(request))  # type: ignore[arg-type]
    assert narrative == ""
