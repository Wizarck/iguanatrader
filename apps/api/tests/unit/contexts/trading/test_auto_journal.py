"""Unit tests for the A3 auto-journal-on-close subscriber.

Pure-unit — no LLM, no DB, no Hindsight network. Fakes the
:class:`JournalWriterLike` and :class:`HindsightClientLike`
dependencies so the handler's two-stage best-effort path is fully
exercised.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from iguanatrader.contexts.trading.auto_journal import AutoJournalOnCloseHandler
from iguanatrader.contexts.trading.events import TradeClosed


def _event(trade_id: UUID | None = None) -> TradeClosed:
    return TradeClosed(
        tenant_id=uuid4(),
        trade_id=trade_id or uuid4(),
        symbol="NVDA",
        side="buy",
        quantity=Decimal("10"),
        realised_pnl=Decimal("237.50"),
        exit_reason="target",
        closed_at=datetime(2026, 5, 18, 12, 30, tzinfo=UTC),
    )


class _FakeWriter:
    def __init__(
        self, *, narrative: str = "Sample narrative.", raises: Exception | None = None
    ) -> None:
        self._narrative = narrative
        self._raises = raises
        self.calls: list[UUID] = []

    async def write_and_persist(self, *, trade_id: UUID) -> str:
        self.calls.append(trade_id)
        if self._raises is not None:
            raise self._raises
        return self._narrative


class _FakeHindsight:
    def __init__(self, *, raises: Exception | None = None) -> None:
        self._raises = raises
        self.retains: list[dict[str, Any]] = []

    async def retain(
        self,
        *,
        bank: str,
        kind: str,
        content: str,
        metadata: dict[str, object],
    ) -> None:
        if self._raises is not None:
            raise self._raises
        self.retains.append({"bank": bank, "kind": kind, "content": content, "metadata": metadata})


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_handler_writes_journal_and_retains_to_hindsight() -> None:
    writer = _FakeWriter(narrative="Solid swing, target hit at +$237.")
    hindsight = _FakeHindsight()
    handler = AutoJournalOnCloseHandler(journal_writer=writer, hindsight_client=hindsight)
    event = _event()

    _run(handler(event))

    assert writer.calls == [event.trade_id]
    assert len(hindsight.retains) == 1
    retain = hindsight.retains[0]
    assert retain["bank"] == "iguanatrader"
    assert retain["kind"] == "trade_journal"
    assert retain["content"] == "Solid swing, target hit at +$237."
    meta = retain["metadata"]
    assert isinstance(meta, dict)
    assert meta["symbol"] == "NVDA"
    assert meta["exit_reason"] == "target"
    assert meta["realised_pnl"] == "237.50"
    assert meta["trade_id"] == str(event.trade_id)


def test_handler_uses_noop_hindsight_when_none_injected() -> None:
    """The default Hindsight client is a logging no-op so the handler
    works in environments where the in-process client isn't wired
    yet. The narrative still persists via the writer."""
    writer = _FakeWriter(narrative="x")
    handler = AutoJournalOnCloseHandler(journal_writer=writer)  # no hindsight
    event = _event()

    # Must NOT raise even though no hindsight client was injected.
    _run(handler(event))
    assert writer.calls == [event.trade_id]


# ---------------------------------------------------------------------------
# Best-effort degradation paths
# ---------------------------------------------------------------------------


def test_writer_failure_swallowed_no_hindsight_call() -> None:
    """LLM / persistence failure → narrative stays NULL on the trade
    row + structlog event. Hindsight retain must NOT fire (no
    narrative to retain)."""
    writer = _FakeWriter(raises=RuntimeError("Anthropic 429"))
    hindsight = _FakeHindsight()
    handler = AutoJournalOnCloseHandler(journal_writer=writer, hindsight_client=hindsight)

    _run(handler(_event()))

    assert hindsight.retains == []


def test_hindsight_failure_swallowed_narrative_already_persisted() -> None:
    """Hindsight network error → narrative still on the trade row
    (writer already returned successfully); only the retain leg is
    skipped."""
    writer = _FakeWriter(narrative="persisted")
    hindsight = _FakeHindsight(raises=ConnectionError("hermes 503"))
    handler = AutoJournalOnCloseHandler(journal_writer=writer, hindsight_client=hindsight)

    # Must NOT raise.
    _run(handler(_event()))
    assert writer.calls != []


def test_writer_returns_empty_string_skips_hindsight() -> None:
    """Writer's idempotent-second-call path returns empty; no point
    pushing an empty narrative into the recall bank."""
    writer = _FakeWriter(narrative="")
    hindsight = _FakeHindsight()
    handler = AutoJournalOnCloseHandler(journal_writer=writer, hindsight_client=hindsight)

    _run(handler(_event()))
    assert hindsight.retains == []


# ---------------------------------------------------------------------------
# Event shape regression
# ---------------------------------------------------------------------------


def test_trade_closed_idempotency_key_derived_from_trade_id() -> None:
    """The bus dedupes deliveries via ``idempotency_key``; the event's
    ``__post_init__`` MUST default it from ``trade_id`` so a repeated
    delivery of the same close doesn't double-journal."""
    trade_id = uuid4()
    event = TradeClosed(
        tenant_id=uuid4(),
        trade_id=trade_id,
        symbol="X",
        side="buy",
        quantity=Decimal("1"),
        realised_pnl=Decimal("0"),
        exit_reason="manual",
        closed_at=datetime(2026, 5, 18, tzinfo=UTC),
    )
    assert event.idempotency_key == f"trade-closed:{trade_id}"
