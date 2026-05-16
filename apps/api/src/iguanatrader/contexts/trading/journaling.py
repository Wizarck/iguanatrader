"""``TradeJournalWriter`` — LLM-generated post-mortem journal.

After a trade closes, the operator can POST
``/api/v1/trades/{id}/journal`` to ask the LLM to produce a 2-4
paragraph post-mortem: what worked, what didn't, lessons. The
narrative persists on the ``trades.journal_narrative`` column
(migration 0018); the endpoint short-circuits with HTTP 409 when the
column is non-NULL unless ``?regenerate=true`` is set.

Tagged ``application=iguanatrader-journal`` in Langfuse so the ELIGIA
``Top by Application`` widget shows journal spend separately. Default
model is ``claude-3-5-haiku`` — the task is narrative summarisation,
not novel reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import structlog

from iguanatrader.contexts.research.synthesis.llm_client import LLMClient

log = structlog.get_logger("iguanatrader.contexts.trading.journaling")

#: Default model — narrative summarisation; haiku is sufficient.
DEFAULT_JOURNAL_MODEL = "claude-3-5-haiku-20241022"

#: Output token ceiling. Journal narratives are 2-4 paragraphs.
JOURNAL_MAX_TOKENS = 1000

PROMPT_TEMPLATE = """\
You are a trading-journal assistant. The user wants a post-mortem
narrative for a closed trade. Write 2-4 short paragraphs in English
covering:

1. What this trade aimed to do (infer from side + symbol + entry/stop).
2. How it went (entry filled, ran for N bars, closed via {exit_reason}).
3. What worked or didn't (e.g. stop hit fast = thesis broke quickly).
4. One concrete lesson the operator might extract.

Be specific to the data; do not generalise. Plain markdown only. Do
NOT include preamble like "Here's the journal entry…".

# Trade

* Symbol: {symbol}
* Side: {side}
* Quantity: {quantity}
* Mode: {mode}
* Opened: {opened_at}
* Closed: {closed_at}
* Exit reason: {exit_reason}
* Realised P&L: {realised_pnl}
"""


@dataclass(frozen=True, slots=True)
class TradeJournalResult:
    """Service-level return; route layer maps to the DTO + persists."""

    trade_id: str
    narrative: str
    model: str
    generated_at: datetime
    tokens_input: int
    tokens_output: int


class TradeJournalWriter:
    """Produces a post-mortem narrative for a closed trade."""

    def __init__(
        self,
        llm_client: LLMClient,
        *,
        model: str = DEFAULT_JOURNAL_MODEL,
    ) -> None:
        self._llm = llm_client
        self._model = model

    async def write(
        self,
        *,
        trade_id: str,
        symbol: str,
        side: str,
        quantity: Decimal,
        mode: str,
        opened_at: datetime,
        closed_at: datetime | None,
        exit_reason: str | None,
        realised_pnl: Decimal | None,
    ) -> TradeJournalResult:
        """Render the prompt + call the LLM + wrap the response."""
        prompt = PROMPT_TEMPLATE.format(
            symbol=symbol,
            side=side,
            quantity=str(quantity),
            mode=mode,
            opened_at=opened_at.isoformat(),
            closed_at=closed_at.isoformat() if closed_at else "still open",
            exit_reason=exit_reason or "unknown",
            realised_pnl=(str(realised_pnl) if realised_pnl is not None else "not yet realised"),
        )
        completion = await self._llm.complete(
            prompt=prompt,
            model=self._model,
            replay_key=None,
            max_tokens=JOURNAL_MAX_TOKENS,
            langfuse_application="iguanatrader-journal",
        )
        log.info(
            "trading.journaling.completed",
            trade_id=trade_id,
            model=self._model,
            tokens_input=completion.tokens_input,
            tokens_output=completion.tokens_output,
        )
        return TradeJournalResult(
            trade_id=trade_id,
            narrative=completion.text.strip(),
            model=completion.model,
            generated_at=datetime.now(UTC),
            tokens_input=completion.tokens_input,
            tokens_output=completion.tokens_output,
        )


__all__ = [
    "DEFAULT_JOURNAL_MODEL",
    "JOURNAL_MAX_TOKENS",
    "TradeJournalResult",
    "TradeJournalWriter",
]
