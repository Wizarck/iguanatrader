"""Auto-journal subscriber — slice A3 (keystone of LLM features track).

Subscribes to :class:`TradeClosed`; on every trade close, invokes the
:class:`TradeJournalWriter` (already shipped in #194) and persists the
narrative on ``trades.journal_narrative``. The Hindsight retain leg
described in the roadmap is wired with a Protocol — production
composition root injects a real client when the in-process Python
``HindsightClient`` lands in a follow-up; until then a no-op stub
keeps the handler invocable.

Best-effort semantics (per roadmap A3 §Components):

* LLM failure (timeout, budget exceeded, parse error) → narrative
  stays NULL on the trade row + ``trading.auto_journal.failed``
  structlog event. The close is NEVER rolled back.
* Hindsight retain failure → narrative still persists on the trade
  row; only the recall-bank write is skipped. ``trading.auto_journal.hindsight_failed``
  structlog event for postmortems.
* A1 / A2 dispatcher consumers of `journal_narrative` for the
  current trade are unaffected — they read whatever is on the row.

The handler does NOT consult the budget guard directly; the guard
sits inside ``route_llm`` (slice R6) which the
:class:`TradeJournalWriter` calls internally. A ``BLOCK_100`` cap
hit therefore surfaces here as the same LLM-failure path above.
"""

from __future__ import annotations

import logging
from typing import Protocol
from uuid import UUID

from iguanatrader.contexts.trading.events import TradeClosed

logger = logging.getLogger(__name__)


class HindsightClientLike(Protocol):
    """Structural type for the in-process Hindsight retain client.

    Real implementation arrives in a follow-up slice. The Protocol
    here lets the auto-journal handler compose against the contract
    without depending on the concrete class.
    """

    async def retain(
        self,
        *,
        bank: str,
        kind: str,
        content: str,
        metadata: dict[str, object],
    ) -> None: ...


class _NoopHindsightClient:
    """Fallback when the production client isn't wired yet.

    Logs an event so an operator inspecting structlog can confirm the
    auto-journal handler is running even though the retain leg is
    inert. Returns successfully so the handler treats the call as
    a no-op success.
    """

    async def retain(
        self,
        *,
        bank: str,
        kind: str,
        content: str,
        metadata: dict[str, object],
    ) -> None:
        logger.info(
            "trading.auto_journal.hindsight_noop",
            extra={"bank": bank, "kind": kind, "metadata": metadata},
        )


class JournalWriterLike(Protocol):
    """Structural type for the journal writer surface we consume.

    Mirrors the public method on the production
    :class:`TradeJournalWriter` so tests can inject a fake without
    pulling the full LLM client stack.
    """

    async def write_and_persist(
        self,
        *,
        trade_id: UUID,
    ) -> str: ...


class AutoJournalOnCloseHandler:
    """Bus subscriber for :class:`TradeClosed`.

    Construction takes the journal writer + Hindsight client as
    explicit dependencies; the composition root binds the production
    pair, while tests inject fakes.
    """

    def __init__(
        self,
        *,
        journal_writer: JournalWriterLike,
        hindsight_client: HindsightClientLike | None = None,
    ) -> None:
        self._writer = journal_writer
        self._hindsight = hindsight_client or _NoopHindsightClient()

    async def __call__(self, event: TradeClosed) -> None:
        """Bus delivers ``TradeClosed`` instances here.

        Two-stage best-effort:

        1. ``write_and_persist`` — generates the narrative + persists
           it on ``trades.journal_narrative``. Returns the narrative
           text on success; raises on any failure (LLM, persistence,
           tenant lookup, etc.). We log + swallow.
        2. ``hindsight.retain`` — pushes the narrative into the
           ``iguanatrader`` Hindsight bank for cross-conversation
           recall. Independent best-effort; failure does NOT roll
           back the journal narrative already on the row.
        """
        narrative: str | None = None
        try:
            narrative = await self._writer.write_and_persist(trade_id=event.trade_id)
        except Exception as exc:
            logger.warning(
                "trading.auto_journal.failed",
                extra={
                    "trade_id": str(event.trade_id),
                    "symbol": event.symbol,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            return

        if not narrative:
            # Writer returned the empty string — same surface as the
            # idempotent-second-call path; nothing to retain.
            return

        try:
            await self._hindsight.retain(
                bank="iguanatrader",
                kind="trade_journal",
                content=narrative,
                metadata={
                    "symbol": event.symbol,
                    "side": event.side,
                    "realised_pnl": str(event.realised_pnl),
                    "exit_reason": event.exit_reason,
                    "trade_id": str(event.trade_id),
                    "closed_at": event.closed_at.isoformat(),
                },
            )
        except Exception as exc:
            logger.warning(
                "trading.auto_journal.hindsight_failed",
                extra={
                    "trade_id": str(event.trade_id),
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )


__all__ = [
    "AutoJournalOnCloseHandler",
    "HindsightClientLike",
    "JournalWriterLike",
]
