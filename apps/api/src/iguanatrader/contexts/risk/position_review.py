"""Position-review read model — reconcile DB-intended stops/targets against
the protective orders ACTUALLY resting at the broker.

Slice ``position-review-broker-visibility`` (WS-5 PR-A). The owner wants the
daemon (and a one-shot CLI) to answer, for every open position: how many do I
hold, what stop-loss / take-profit did the strategy intend, and what is
ACTUALLY configured at Interactive Brokers right now? Divergence between the
two (a stop that the DB expects but is NOT resting at the broker, a level that
drifted, an orphan the broker no longer holds) is exactly the signal the later
urgent-exit advisor (PR-C) feeds to the LLM.

This module is strictly READ-ONLY: it queries open trades + the broker book
and computes a reconciliation. It NEVER places, cancels, or closes anything.
The pure :func:`reconcile_positions` holds all the matching/divergence logic so
it is trivially unit-testable without a DB or a live broker; the thin
:class:`PositionReviewService` only wires the DB enumeration + broker reads to
it (mirroring :class:`~iguanatrader.contexts.risk.stop_hit_sweep.StopHitSweepService`'s
session handling + effective-stop resolution).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, cast
from uuid import UUID

from sqlalchemy import select

from iguanatrader.contexts.risk.trailing_stop_repository import TrailingStopAuditRepository
from iguanatrader.contexts.trading.models import Trade, TradeProposal
from iguanatrader.contexts.trading.ports import BrokerPort, Position, WorkingOrder

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: Relative tolerance for "the resting stop/target level matches the intended
#: one". Broker rounding + tick-size snapping mean an exact compare is too
#: brittle; 0.5 % (floored at 1 cent) treats a stop within half a percent of
#: intent as "in place", anything further as a drift divergence.
_LEVEL_TOLERANCE_PCT: Decimal = Decimal("0.005")
_LEVEL_TOLERANCE_FLOOR: Decimal = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class OpenTradeLevels:
    """One open trade projected to the fields the reconcile needs."""

    trade_id: UUID
    tenant_id: UUID
    symbol: str
    side: str  # "buy" (long) / "sell" (short).
    quantity: Decimal
    intended_stop: Decimal
    intended_target: Decimal | None


@dataclass(frozen=True, slots=True)
class ProtectiveLeg:
    """A protective order resting at the broker, matched to a position."""

    kind: str  # "stop" / "target".
    order_type: str  # "STP" / "STP LMT" / "LMT".
    level: Decimal | None  # Stop trigger (auxPrice) or take-profit limit.
    quantity: Decimal
    status: str
    order_ref: str | None


@dataclass(frozen=True, slots=True)
class PositionReview:
    """Reconciliation of one open position: intended vs broker-resting."""

    trade_id: UUID
    tenant_id: UUID
    symbol: str
    side: str  # "long" / "short".
    quantity: Decimal  # DB trade size.
    intended_stop: Decimal
    intended_target: Decimal | None
    resting_stop: ProtectiveLeg | None
    resting_target: ProtectiveLeg | None
    broker_quantity: Decimal | None  # Signed broker position size (None = absent).
    average_price: Decimal | None
    unrealized_pnl: Decimal | None
    divergences: list[str] = field(default_factory=list)

    @property
    def has_divergence(self) -> bool:
        return bool(self.divergences)


@dataclass(frozen=True, slots=True)
class PositionReviewResult:
    """Counters + the per-position reviews from one read."""

    reviews: list[PositionReview]
    broker_positions_read: int
    broker_working_orders_read: int

    @property
    def divergences_detected(self) -> int:
        return sum(1 for r in self.reviews if r.has_divergence)


def _exit_action_for_side(side: str) -> str:
    """IBKR action that CLOSES a position of ``side`` (a long exits SELL)."""
    return "SELL" if side == "buy" else "BUY"


def _levels_match(intended: Decimal, resting: Decimal) -> bool:
    tol = max(_LEVEL_TOLERANCE_FLOOR, abs(intended) * _LEVEL_TOLERANCE_PCT)
    return abs(intended - resting) <= tol


def _classify_leg(order: WorkingOrder) -> str | None:
    """Return ``"stop"`` / ``"target"`` for a protective order, else ``None``.

    A stop carries ``STP`` in its type (``STP`` or ``STP LMT``); a plain
    ``LMT`` resting on the exit side is the take-profit. Anything else
    (a market exit, an unrelated type) is not a protective level we track.
    """
    otype = order.order_type.upper()
    if "STP" in otype:
        return "stop"
    if "LMT" in otype:
        return "target"
    return None


def reconcile_positions(
    *,
    open_trades: list[OpenTradeLevels],
    broker_positions: list[Position],
    working_orders: list[WorkingOrder],
) -> list[PositionReview]:
    """Pure reconcile: match each open trade to its broker position + the
    protective orders resting on its exit side, and flag divergences.

    Matching is by ``symbol`` + the exit-side action (a long position's
    protective legs are SELL orders). The propose-time
    ``has_open_position(symbol)`` dedup guard means at most one open trade per
    symbol, so symbol+action is unambiguous; if two open trades share a symbol
    the legs cannot be safely attributed and an ``ambiguous_*`` divergence is
    raised rather than guessing (matches the WS-5 design's risk #2).
    """
    # Index broker positions by symbol (absolute qty + avg cost + uPnL).
    pos_by_symbol: dict[str, Position] = {p.symbol: p for p in broker_positions}
    symbols_with_multiple_trades = {
        t.symbol for t in open_trades if sum(1 for o in open_trades if o.symbol == t.symbol) > 1
    }

    reviews: list[PositionReview] = []
    for trade in open_trades:
        side = "long" if trade.side == "buy" else "short"
        exit_action = _exit_action_for_side(trade.side)
        ambiguous = trade.symbol in symbols_with_multiple_trades

        stops: list[ProtectiveLeg] = []
        targets: list[ProtectiveLeg] = []
        if not ambiguous:
            for wo in working_orders:
                if wo.symbol != trade.symbol or wo.action != exit_action:
                    continue
                kind = _classify_leg(wo)
                if kind is None:
                    continue
                leg = ProtectiveLeg(
                    kind=kind,
                    order_type=wo.order_type,
                    level=wo.stop_price if kind == "stop" else wo.limit_price,
                    quantity=wo.quantity,
                    status=wo.status,
                    order_ref=wo.order_ref,
                )
                (stops if kind == "stop" else targets).append(leg)

        resting_stop = stops[0] if stops else None
        resting_target = targets[0] if targets else None

        broker_pos = pos_by_symbol.get(trade.symbol)
        broker_qty = abs(broker_pos.quantity) if broker_pos is not None else None

        divergences: list[str] = []
        if ambiguous:
            divergences.append("ambiguous_multiple_open_trades_same_symbol")
        else:
            if len(stops) > 1:
                divergences.append("ambiguous_multiple_resting_stops")
            if len(targets) > 1:
                divergences.append("ambiguous_multiple_resting_targets")

        if broker_pos is None:
            # DB says open but the broker holds nothing — orphan / manually
            # flat-closed in TWS. Strong urgent signal for the exit advisor.
            divergences.append("no_broker_position")
        elif broker_qty is not None and broker_qty != trade.quantity:
            divergences.append("position_size_mismatch")

        if not ambiguous:
            if resting_stop is None:
                # Intended a protective stop but none is resting — the position
                # is unprotected at the broker right now.
                divergences.append("stop_missing_at_broker")
            elif resting_stop.level is None or not _levels_match(
                trade.intended_stop, resting_stop.level
            ):
                divergences.append("stop_level_mismatch")

            if trade.intended_target is not None:
                if resting_target is None:
                    divergences.append("target_missing_at_broker")
                elif resting_target.level is None or not _levels_match(
                    trade.intended_target, resting_target.level
                ):
                    divergences.append("target_level_mismatch")

        reviews.append(
            PositionReview(
                trade_id=trade.trade_id,
                tenant_id=trade.tenant_id,
                symbol=trade.symbol,
                side=side,
                quantity=trade.quantity,
                intended_stop=trade.intended_stop,
                intended_target=trade.intended_target,
                resting_stop=resting_stop,
                resting_target=resting_target,
                broker_quantity=broker_pos.quantity if broker_pos is not None else None,
                average_price=broker_pos.average_price if broker_pos is not None else None,
                unrealized_pnl=broker_pos.unrealized_pnl if broker_pos is not None else None,
                divergences=divergences,
            )
        )
    return reviews


class PositionReviewService:
    """Wire the DB open-trade enumeration + broker reads to the pure reconcile.

    Read-only. Reused by the WS-5 urgent-exit cron (PR-C) and the
    ``positions-review`` CLI. Session handling mirrors
    :class:`StopHitSweepService`: pass ``session=`` explicitly (tests) or leave
    it to resolve the per-tick session from ``session_var`` (cron scope).
    """

    def __init__(
        self,
        *,
        broker: BrokerPort,
        session: AsyncSession | None = None,
        trailing_audit_repo: TrailingStopAuditRepository | None = None,
    ) -> None:
        self._broker = broker
        self._explicit_session = session
        self._trailing_audit_repo = trailing_audit_repo

    @property
    def _session(self) -> AsyncSession:
        if self._explicit_session is not None:
            return self._explicit_session
        from iguanatrader.shared.contextvars import session_var

        sess = session_var.get()
        if sess is None:
            raise LookupError(
                "PositionReviewService has no session: pass session=... or bind "
                "session_var (per-tick cron scope)."
            )
        return cast("AsyncSession", sess)

    async def review(self) -> PositionReviewResult:
        open_trades = await self._list_open_trades_with_levels()
        broker_positions = list(await self._broker.list_positions())
        working_orders = list(await self._broker.list_working_orders())
        reviews = reconcile_positions(
            open_trades=open_trades,
            broker_positions=broker_positions,
            working_orders=working_orders,
        )
        logger.info(
            "risk.position_review.completed",
            extra={
                "open_trades": len(open_trades),
                "broker_positions": len(broker_positions),
                "broker_working_orders": len(working_orders),
                "divergences": sum(1 for r in reviews if r.has_divergence),
            },
        )
        return PositionReviewResult(
            reviews=reviews,
            broker_positions_read=len(broker_positions),
            broker_working_orders_read=len(working_orders),
        )

    async def _list_open_trades_with_levels(self) -> list[OpenTradeLevels]:
        """Open trades joined to their proposal's stop + target, with the
        EFFECTIVE stop resolved (latest trailing-tightened stop else the
        proposal's original — same #28 logic as the stop-hit sweep)."""
        stmt = (
            select(
                Trade.id,
                Trade.tenant_id,
                Trade.symbol,
                Trade.side,
                Trade.quantity,
                TradeProposal.stop_price,
                TradeProposal.target_price,
            )
            .join(TradeProposal, TradeProposal.id == Trade.proposal_id)
            .where(Trade.state == "open")
        )
        result = await self._session.execute(stmt)
        rows: list[OpenTradeLevels] = []
        for trade_id, tenant_id, symbol, side, qty, stop_raw, target_raw in result.all():
            intended_stop = await self._effective_stop(
                trade_id=trade_id, proposal_stop=Decimal(str(stop_raw))
            )
            rows.append(
                OpenTradeLevels(
                    trade_id=trade_id,
                    tenant_id=tenant_id,
                    symbol=symbol,
                    side=side,
                    quantity=Decimal(str(qty)),
                    intended_stop=intended_stop,
                    intended_target=(Decimal(str(target_raw)) if target_raw is not None else None),
                )
            )
        return rows

    async def _effective_stop(self, *, trade_id: UUID, proposal_stop: Decimal) -> Decimal:
        if self._trailing_audit_repo is None:
            return proposal_stop
        latest = await self._trailing_audit_repo.get_latest_for_trade(trade_id)
        if latest is None or latest.new_stop is None:
            return proposal_stop
        return Decimal(str(latest.new_stop))


__all__ = [
    "OpenTradeLevels",
    "PositionReview",
    "PositionReviewResult",
    "PositionReviewService",
    "ProtectiveLeg",
    "reconcile_positions",
]
