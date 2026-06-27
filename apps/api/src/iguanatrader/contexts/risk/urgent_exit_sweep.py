"""Urgent-exit review sweep (WS-5 PR-C) — the cron that ties the program
together.

Each market-hours tick this sweep answers the owner's WS-5 ask: *"when the
cron runs, besides checking pending proposals, review how my open positions
and their REAL stop/take-profit orders at Interactive Brokers look — and if
something signals I should sell URGENTLY, alert me on Telegram to approve or
deny."* It NEVER closes a position directly; it only raises an
:class:`~iguanatrader.contexts.trading.events.ExitApprovalRequested`, which the
approval machinery turns into a Telegram approve/deny card (HITL), and only a
human-granted decision closes the trade.

Pipeline per tick:

1. :class:`~iguanatrader.contexts.risk.position_review.PositionReviewService`
   (PR-A) enumerates every open trade with its intended stop/target and the
   protective orders ACTUALLY resting at the broker, flagging divergences
   (stop missing, level drift, orphan, size mismatch, …).
2. **Pending-exit dedup** — skip a trade that already has an open exit card
   (``ApprovalRepository.has_pending_exit_for_trade``), so a still-unanswered
   alert is not re-sent every 15 minutes. A re-raise flows once the card
   expires (see the event docstring).
3. **Cost pre-filter** — the LLM opinion (Opus) is only worth its cost when
   there is something adverse to reason about, so call the advisor ONLY when
   the position is at an unrealised LOSS *or* the broker reconciliation found a
   divergence. A green, fully-protected position is skipped without an LLM
   call.
4. **Urgent-exit opinion (Opus)** — the
   :class:`~iguanatrader.contexts.research.proposal_advisor.exit_advisor.ExitAdvisor`
   (injected structurally as :class:`ExitAdvisorLike` to keep risk decoupled
   from research) reads the position, its resting protective orders, the
   divergences, the latest fundamental brief thesis, recalled historical
   context, and recent trade outcomes, and returns ``urgent_sell`` +
   ``confidence``.
5. On ``urgent_sell`` above the confidence threshold (default 0.75) publish
   :class:`ExitApprovalRequested` → Telegram approve/deny.

Failure isolation mirrors the other sweeps: a per-position exception is caught
+ logged and the sweep continues to the next trade; the counter result gives
the operator dashboard a "ran but skipped N" view.

Decoupling: this module lives in ``risk`` but the advisor, the brief lookup,
the Hindsight recall, and the recent-trade summary are all INJECTED (Protocols
/ callables) so risk never deep-imports research/approval — the composition
root (``cli/trading.py``) wires the concrete collaborators.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from iguanatrader.contexts.trading.events import ExitApprovalRequested
from iguanatrader.shared.messagebus import MessageBus
from iguanatrader.shared.time import now as utc_now

if TYPE_CHECKING:
    from iguanatrader.contexts.risk.position_review import (
        PositionReview,
        PositionReviewService,
    )

logger = logging.getLogger(__name__)

#: Minimum advisor conviction before an urgent-exit card is raised. A false
#: urgent alarm costs operator trust, so the bar is deliberately high; the
#: advisor is also prompted to default to HOLD when uncertain.
DEFAULT_CONFIDENCE_THRESHOLD: Decimal = Decimal("0.75")


class ExitVerdictLike(Protocol):
    """Structural shape of the advisor's verdict the sweep consumes.

    Members are read-only properties so a ``frozen`` verdict dataclass (the
    concrete ``ExitAdvisorVerdict``) structurally conforms — a frozen attribute
    cannot satisfy a mutable protocol member.
    """

    @property
    def urgent_sell(self) -> bool: ...

    @property
    def confidence(self) -> Decimal: ...

    @property
    def rationale(self) -> str: ...

    @property
    def flags(self) -> list[str]: ...


class ExitAdvisorLike(Protocol):
    """Structural shape of the urgent-exit advisor (concrete: research
    ``ExitAdvisor`` on Opus). Injected so ``risk`` does not import ``research``."""

    async def assess(
        self,
        *,
        trade_id: str,
        symbol: str,
        side: str,
        quantity: Decimal,
        average_price: Decimal | None,
        current_price: Decimal | None,
        unrealized_pnl: Decimal | None,
        intended_stop: Decimal,
        intended_target: Decimal | None,
        resting_orders_summary: str,
        divergences: list[str],
        brief_thesis: str | None,
        hindsight_chunks: list[str],
        recent_trades_summary: str,
    ) -> ExitVerdictLike: ...


@dataclass(frozen=True, slots=True)
class UrgentExitReviewResult:
    """Counters + duration returned from :meth:`UrgentExitReviewSweepService.sweep`."""

    positions_reviewed: int
    candidates_assessed: int  # passed the cost pre-filter → advisor called.
    urgent_exits_raised: int
    skipped_pending: int  # already has an open exit card.
    skipped_no_signal: int  # green + protected → no LLM call.
    skipped_errors: int
    broker_working_orders_read: int
    duration_ms: int


class UrgentExitReviewSweepService:
    """Per-tick urgent-exit reviewer: positions → pre-filter → Opus → HITL card."""

    def __init__(
        self,
        *,
        position_review: PositionReviewService,
        exit_advisor: ExitAdvisorLike,
        bus: MessageBus,
        pending_exit_checker: Callable[[UUID], Awaitable[bool]],
        brief_lookup: Callable[[str], Awaitable[str | None]] | None = None,
        hindsight_lookup: Callable[[str], Awaitable[list[str]]] | None = None,
        recent_trades_lookup: Callable[[str], Awaitable[str]] | None = None,
        confidence_threshold: Decimal = DEFAULT_CONFIDENCE_THRESHOLD,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._position_review = position_review
        self._advisor = exit_advisor
        self._bus = bus
        self._has_pending_exit = pending_exit_checker
        self._brief_lookup = brief_lookup
        self._hindsight_lookup = hindsight_lookup
        self._recent_trades_lookup = recent_trades_lookup
        self._threshold = confidence_threshold
        self._clock = clock

    async def sweep(self) -> UrgentExitReviewResult:
        started_at = self._clock()
        review_result = await self._position_review.review()

        candidates = 0
        raised = 0
        skipped_pending = 0
        skipped_no_signal = 0
        skipped_errors = 0

        for review in review_result.reviews:
            try:
                outcome = await self._evaluate_one(review)
            except Exception as exc:
                logger.warning(
                    "risk.urgent_exit_sweep.position_failed: %s: %s",
                    type(exc).__name__,
                    exc,
                    extra={"symbol": review.symbol, "trade_id": str(review.trade_id)},
                )
                skipped_errors += 1
                continue

            if outcome == "raised":
                candidates += 1
                raised += 1
            elif outcome == "hold":
                candidates += 1
            elif outcome == "pending":
                skipped_pending += 1
            elif outcome == "no_signal":
                skipped_no_signal += 1

        ended_at = self._clock()
        duration_ms = int((ended_at - started_at).total_seconds() * 1000)

        logger.info(
            "risk.urgent_exit_sweep.completed",
            extra={
                "positions_reviewed": len(review_result.reviews),
                "candidates_assessed": candidates,
                "urgent_exits_raised": raised,
                "skipped_pending": skipped_pending,
                "skipped_no_signal": skipped_no_signal,
                "skipped_errors": skipped_errors,
                "duration_ms": duration_ms,
            },
        )

        return UrgentExitReviewResult(
            positions_reviewed=len(review_result.reviews),
            candidates_assessed=candidates,
            urgent_exits_raised=raised,
            skipped_pending=skipped_pending,
            skipped_no_signal=skipped_no_signal,
            skipped_errors=skipped_errors,
            broker_working_orders_read=review_result.broker_working_orders_read,
            duration_ms=duration_ms,
        )

    async def _evaluate_one(self, review: PositionReview) -> str:
        """Evaluate one reviewed position. Returns the outcome bucket:
        ``"pending"`` / ``"no_signal"`` / ``"hold"`` / ``"raised"``."""
        # 1. Pending-exit dedup — don't re-alert while a card is still open.
        if await self._has_pending_exit(review.trade_id):
            return "pending"

        # 2. Cost pre-filter — only spend an Opus call when there is adverse
        #    evidence to reason about (a loss OR a broker divergence).
        adverse_pnl = review.unrealized_pnl is not None and review.unrealized_pnl < 0
        if not (adverse_pnl or review.has_divergence):
            return "no_signal"

        # 3. Gather context (each source degrades to a neutral default).
        brief_thesis = await self._brief_lookup(review.symbol) if self._brief_lookup else None
        hindsight_chunks = (
            await self._hindsight_lookup(review.symbol) if self._hindsight_lookup else []
        )
        recent_trades = (
            await self._recent_trades_lookup(review.symbol) if self._recent_trades_lookup else ""
        )
        held_side = "buy" if review.side == "long" else "sell"

        # 4. Urgent-exit opinion (Opus).
        verdict = await self._advisor.assess(
            trade_id=str(review.trade_id),
            symbol=review.symbol,
            side=held_side,
            quantity=review.quantity,
            average_price=review.average_price,
            current_price=None,
            unrealized_pnl=review.unrealized_pnl,
            intended_stop=review.intended_stop,
            intended_target=review.intended_target,
            resting_orders_summary=_summarise_resting(review),
            divergences=list(review.divergences),
            brief_thesis=brief_thesis,
            hindsight_chunks=hindsight_chunks,
            recent_trades_summary=recent_trades,
        )

        if not (verdict.urgent_sell and verdict.confidence >= self._threshold):
            return "hold"

        # 5. Raise the HITL exit card. NEVER closes directly.
        await self._bus.publish(
            ExitApprovalRequested(
                tenant_id=review.tenant_id,
                trade_id=review.trade_id,
                symbol=review.symbol,
                side=held_side,
                quantity=review.quantity,
                reason="urgent",
                llm_rationale=verdict.rationale,
                confidence=verdict.confidence,
                metadata={
                    "divergences": list(review.divergences),
                    "flags": list(verdict.flags),
                    "unrealized_pnl": (
                        str(review.unrealized_pnl) if review.unrealized_pnl is not None else None
                    ),
                },
            )
        )
        logger.info(
            "risk.urgent_exit_sweep.exit_card_raised",
            extra={
                "trade_id": str(review.trade_id),
                "symbol": review.symbol,
                "side": held_side,
                "confidence": str(verdict.confidence),
                "divergences": list(review.divergences),
            },
        )
        return "raised"


def _summarise_resting(review: PositionReview) -> str:
    """Human-readable one-liner of the protective orders resting at the broker,
    for the advisor prompt (``"none observed"`` when the position is naked)."""
    parts: list[str] = []
    if review.resting_stop is not None:
        leg = review.resting_stop
        parts.append(
            f"stop {leg.order_type} @ {leg.level if leg.level is not None else 'unknown'} "
            f"(qty {leg.quantity}, {leg.status})"
        )
    if review.resting_target is not None:
        leg = review.resting_target
        parts.append(
            f"target {leg.order_type} @ {leg.level if leg.level is not None else 'unknown'} "
            f"(qty {leg.quantity}, {leg.status})"
        )
    return "; ".join(parts) if parts else "none observed"


__all__ = [
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "ExitAdvisorLike",
    "ExitVerdictLike",
    "UrgentExitReviewResult",
    "UrgentExitReviewSweepService",
]
