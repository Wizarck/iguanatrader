"""``EntryVetoGate`` — the WS-2 hard pre-filter wired into ``propose()``.

Bridges the Opus :class:`EntryAdvisor` with the context it needs (latest brief
thesis, gated Hindsight recall, recent trade outcomes) and turns its verdict
into a simple ``blocked`` decision the trading service consumes through a
Protocol (so trading never deep-imports research). Mirrors the WS-5 exit sweep's
injection style: the advisor + lookups are injected; the composition root wires
the concrete collaborators.

Policy:

* ``blocked`` iff the advisor vetoes AND its confidence clears the threshold
  (default 0.75) — the same high bar as the exit advisor, because blocking a
  good entry costs the owner opportunity.
* **Fail-OPEN**: any error gathering context or calling the LLM yields
  ``blocked=False``. A gate hiccup (LLM timeout, budget, Hindsight outage) must
  never silently suppress trading — the human Telegram approval is still the
  backstop downstream. The error is logged, not swallowed into a block.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from iguanatrader.contexts.research.proposal_advisor.entry_advisor import EntryAdvisor

logger = logging.getLogger(__name__)

#: Minimum advisor conviction before an entry is blocked. High by design —
#: a false veto costs the owner a good trade.
DEFAULT_VETO_THRESHOLD: Decimal = Decimal("0.75")


@dataclass(frozen=True, slots=True)
class EntryGateDecision:
    """Outcome of the entry gate for one proposal."""

    blocked: bool
    rationale: str
    confidence: Decimal
    flags: list[str] = field(default_factory=list)


class EntryVetoGate:
    """Per-proposal entry pre-filter: gather context → Opus → block / proceed."""

    def __init__(
        self,
        advisor: EntryAdvisor,
        *,
        brief_lookup: Callable[[str], Awaitable[str | None]] | None = None,
        hindsight_lookup: Callable[[str], Awaitable[list[str]]] | None = None,
        recent_trades_lookup: Callable[[str], Awaitable[str]] | None = None,
        confidence_threshold: Decimal = DEFAULT_VETO_THRESHOLD,
    ) -> None:
        self._advisor = advisor
        self._brief_lookup = brief_lookup
        self._hindsight_lookup = hindsight_lookup
        self._recent_trades_lookup = recent_trades_lookup
        self._threshold = confidence_threshold

    async def evaluate(
        self,
        *,
        symbol: str,
        side: str,
        quantity: Decimal,
        entry_price: Decimal | None,
        stop_price: Decimal | None,
        target_price: Decimal | None,
        confidence_score: Decimal | None,
        reasoning: dict[str, Any],
    ) -> EntryGateDecision:
        try:
            brief_thesis = await self._brief_lookup(symbol) if self._brief_lookup else None
            hindsight_chunks = (
                await self._hindsight_lookup(symbol) if self._hindsight_lookup else []
            )
            recent_trades = (
                await self._recent_trades_lookup(symbol) if self._recent_trades_lookup else ""
            )
            verdict = await self._advisor.assess(
                symbol=symbol,
                side=side,
                quantity=quantity,
                entry_price=entry_price,
                stop_price=stop_price,
                target_price=target_price,
                confidence_score=confidence_score,
                reasoning=reasoning,
                brief_thesis=brief_thesis,
                hindsight_chunks=hindsight_chunks,
                recent_trades_summary=recent_trades,
            )
        except Exception as exc:
            # Fail-open: never block trading on a gate error. The human HITL
            # approval remains the backstop.
            logger.warning(
                "research.entry_gate.failed_open: %s: %s",
                type(exc).__name__,
                exc,
                extra={"symbol": symbol},
            )
            return EntryGateDecision(
                blocked=False,
                rationale=f"entry gate error (fail-open): {type(exc).__name__}",
                confidence=Decimal("0"),
            )

        blocked = verdict.veto and verdict.confidence >= self._threshold
        logger.info(
            "research.entry_gate.evaluated",
            extra={
                "symbol": symbol,
                "veto": verdict.veto,
                "confidence": str(verdict.confidence),
                "blocked": blocked,
            },
        )
        return EntryGateDecision(
            blocked=blocked,
            rationale=verdict.rationale,
            confidence=verdict.confidence,
            flags=list(verdict.flags),
        )


__all__ = [
    "DEFAULT_VETO_THRESHOLD",
    "EntryGateDecision",
    "EntryVetoGate",
]
