"""Stop-hit + target-hit sweep service.

Slice ``exit-classification-stop-hit-sweep``. Closes the auto-close
loop in the risk-state pipeline: prior to this slice, ``exit_reason``
was only populated when an operator manually invoked
``POST /trades/{id}/close`` (which threads ``reason`` through to
:meth:`TradingService.close_trade`). Stop-loss and take-profit hits
never fired automatically — the trailing-stops sweep ratcheted stops
but did not act on them, and there was no equivalent loop watching
the static stop / target either. As a result, K1's stoploss_guard
protection (which reads ``Trade.exit_reason == 'stop'`` to count
recent stop-outs) silently saw zero hits no matter how many losses
the strategy took.

This sweep watches every open trade per cron tick:

1. Joins :class:`Trade` → :class:`TradeProposal` to obtain the
   proposal-stamped ``stop_price`` (mandatory) + ``target_price``
   (nullable, added in migration 0025 for take-profit detection).
2. Fetches the latest bar via :class:`MarketDataPort` (production:
   ``DBMarketDataAdapter`` reads from ``market_data_bars``; tests
   pass an in-memory fake).
3. Compares the bar's close to the stop / target with side-aware
   semantics:

   * Long (``trade.side == "buy"``):
     * stop_hit iff ``close <= stop_price``
     * target_hit iff ``target_price is not None`` and ``close >= target_price``
   * Short (``trade.side == "sell"``):
     * stop_hit iff ``close >= stop_price``
     * target_hit iff ``target_price is not None`` and ``close <= target_price``

4. Publishes :class:`CloseTradeRequested` with ``reason="stop"`` or
   ``reason="target"`` — :meth:`TradingService.close_trade_handler`
   picks it up and submits the exit order. The handler is idempotent
   at ``state="closing"`` so a second sweep tick that re-detects the
   condition before the broker fills the exit is a no-op.

Failure isolation: per-trade exceptions (missing bars, market-data
adapter outage, broker timeout) are caught + logged; the sweep
continues to the next trade. The whole-sweep counter row gives the
operator dashboard a "ran but skipped 3 / 7" visibility.

Registered as a cron job by
:meth:`OrchestrationService.bootstrap_routines` at 1-minute cadence
during US market hours (more aggressive than the 15-min trailing-
stops sweep — stop hits need fast reaction). Reach for a slower
cadence by overriding the ``cron_kwargs`` at registration; reach for
a faster one by adding a strategy-level event-driven loop (out of
scope here).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select

from iguanatrader.contexts.risk.trailing_stop_repository import TrailingStopAuditRepository
from iguanatrader.contexts.trading.events import CloseTradeRequested
from iguanatrader.contexts.trading.models import Trade, TradeProposal
from iguanatrader.contexts.trading.ports import MarketDataPort
from iguanatrader.shared.messagebus import MessageBus
from iguanatrader.shared.time import now as utc_now

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StopHitSweepResult:
    """Counters + duration returned from :meth:`StopHitSweepService.sweep`."""

    trades_evaluated: int
    stop_hits_emitted: int
    target_hits_emitted: int
    trades_skipped_no_bars: int
    duration_ms: int


@dataclass(frozen=True, slots=True)
class _TradeWithExitLevels:
    """Compact projection used by the per-tick loop."""

    trade_id: object  # UUID at runtime; Mapped[Any] in the model.
    tenant_id: object
    symbol: str
    side: str
    stop_price: Decimal
    target_price: Decimal | None


class StopHitSweepService:
    """Per-tick orchestrator: open trades → bar lookup → emit close events.

    The service is stateless beyond its injected dependencies; the cron
    caller instantiates one per registration call and reuses it.
    """

    def __init__(
        self,
        *,
        session: AsyncSession,
        market_data_port: MarketDataPort,
        bus: MessageBus,
        clock: Callable[[], datetime] = utc_now,
        timeframe: str = "1d",
        trailing_audit_repo: TrailingStopAuditRepository | None = None,
    ) -> None:
        self._session = session
        self._market_data_port = market_data_port
        self._bus = bus
        self._clock = clock
        self._timeframe = timeframe
        # #28: when injected, the EFFECTIVE stop is the latest tightened
        # ``trailing_stop_audit.new_stop`` rather than the proposal's
        # original stop — otherwise the trailing sweep ratchets the stop in
        # the audit log but the close loop never acts on the tightened
        # level, so trailing stops are never actually enforced. When None
        # (e.g. a tenant with no trailing config), the proposal stop is used
        # unchanged. Production wires the repo in the daemon bootstrap.
        self._trailing_audit_repo = trailing_audit_repo

    async def sweep(self) -> StopHitSweepResult:
        """Iterate open trades, compare to stop/target, emit close events."""
        started_at = self._clock()
        open_trades = await self._list_open_trades_with_levels()

        stop_hits = 0
        target_hits = 0
        skipped = 0

        for record in open_trades:
            try:
                outcome = await self._evaluate_one(record)
            except Exception as exc:
                logger.warning(
                    "risk.stop_hit_sweep.symbol_failed: %s: %s",
                    type(exc).__name__,
                    exc,
                    extra={
                        "symbol": record.symbol,
                        "trade_id": str(record.trade_id),
                    },
                )
                skipped += 1
                continue

            if outcome == "stop":
                stop_hits += 1
            elif outcome == "target":
                target_hits += 1

        ended_at = self._clock()
        duration_ms = int((ended_at - started_at).total_seconds() * 1000)

        logger.info(
            "risk.stop_hit_sweep.completed",
            extra={
                "trades_evaluated": len(open_trades),
                "stop_hits_emitted": stop_hits,
                "target_hits_emitted": target_hits,
                "trades_skipped_no_bars": skipped,
                "duration_ms": duration_ms,
            },
        )

        return StopHitSweepResult(
            trades_evaluated=len(open_trades),
            stop_hits_emitted=stop_hits,
            target_hits_emitted=target_hits,
            trades_skipped_no_bars=skipped,
            duration_ms=duration_ms,
        )

    # ------------------------------------------------------------------
    # Internal — DB lookup + evaluation
    # ------------------------------------------------------------------

    async def _list_open_trades_with_levels(self) -> list[_TradeWithExitLevels]:
        """Return open trades joined to their proposal's stop + target.

        The slice-3 tenant listener auto-filters by ``tenant_id_var``
        when bound; the cron caller (orchestration bootstrap) is
        responsible for setting up the per-tenant context if the daemon
        runs multi-tenant. For single-tenant ops the bound tenant from
        :func:`cli.trading._run_daemon` suffices.
        """
        stmt = (
            select(
                Trade.id,
                Trade.tenant_id,
                Trade.symbol,
                Trade.side,
                TradeProposal.stop_price,
                TradeProposal.target_price,
            )
            .join(TradeProposal, TradeProposal.id == Trade.proposal_id)
            .where(Trade.state == "open")
        )
        result = await self._session.execute(stmt)
        rows: list[_TradeWithExitLevels] = []
        for trade_id, tenant_id, symbol, side, stop_raw, target_raw in result.all():
            rows.append(
                _TradeWithExitLevels(
                    trade_id=trade_id,
                    tenant_id=tenant_id,
                    symbol=symbol,
                    side=side,
                    stop_price=Decimal(str(stop_raw)),
                    target_price=(Decimal(str(target_raw)) if target_raw is not None else None),
                )
            )
        return rows

    async def _effective_stop(self, record: _TradeWithExitLevels) -> Decimal:
        """Return the stop to enforce: latest trailing-tightened stop, else
        the proposal's original (#28).

        The trailing sweep records each ratchet in ``trailing_stop_audit``;
        the most-recent ``new_stop`` is the live protective level. Falling
        back to the proposal stop preserves behaviour for trades that have
        no trailing config (no audit rows).
        """
        if self._trailing_audit_repo is None:
            return record.stop_price
        latest = await self._trailing_audit_repo.get_latest_for_trade(record.trade_id)
        if latest is None or latest.new_stop is None:
            return record.stop_price
        return Decimal(str(latest.new_stop))

    async def _evaluate_one(self, record: _TradeWithExitLevels) -> str | None:
        """Evaluate one trade against the latest bar.

        Returns ``"stop"`` / ``"target"`` on a hit (and publishes the
        :class:`CloseTradeRequested`), or ``None`` when neither
        threshold is breached.
        """
        history = await self._market_data_port.get_bars(
            symbol=record.symbol,
            timeframe="1d",
            lookback_bars=1,
        )
        if not history.bars:
            logger.info(
                "risk.stop_hit_sweep.no_bars",
                extra={"symbol": record.symbol, "trade_id": str(record.trade_id)},
            )
            return None

        latest_close = history.bars[-1].close

        effective_stop = await self._effective_stop(record)
        if _is_stop_hit(side=record.side, close=latest_close, stop=effective_stop):
            await self._publish_close(record=record, reason="stop")
            return "stop"

        if record.target_price is not None and _is_target_hit(
            side=record.side,
            close=latest_close,
            target=record.target_price,
        ):
            await self._publish_close(record=record, reason="target")
            return "target"

        return None

    async def _publish_close(
        self,
        *,
        record: _TradeWithExitLevels,
        reason: str,
    ) -> None:
        # ``CloseTradeRequested`` uses ``trade_id`` as the idempotency
        # key (see events.py:__post_init__), so a duplicate publish in
        # the same tick window is a no-op at the bus.
        from uuid import UUID

        tenant = (
            record.tenant_id if isinstance(record.tenant_id, UUID) else UUID(str(record.tenant_id))
        )
        trade = record.trade_id if isinstance(record.trade_id, UUID) else UUID(str(record.trade_id))
        await self._bus.publish(
            CloseTradeRequested(
                tenant_id=tenant,
                trade_id=trade,
                reason=reason,
            )
        )
        logger.info(
            "risk.stop_hit_sweep.close_requested",
            extra={
                "trade_id": str(trade),
                "symbol": record.symbol,
                "reason": reason,
            },
        )


def _is_stop_hit(*, side: str, close: Decimal, stop: Decimal) -> bool:
    """Side-aware stop comparison. Pure — easy to unit-test."""
    if side == "buy":
        return close <= stop
    if side == "sell":
        return close >= stop
    # Defensive default: unknown side never fires (operator sees zero
    # in the counter rather than a false close).
    return False


def _is_target_hit(*, side: str, close: Decimal, target: Decimal) -> bool:
    """Side-aware target comparison. Pure — easy to unit-test."""
    if side == "buy":
        return close >= target
    if side == "sell":
        return close <= target
    return False


__all__ = [
    "StopHitSweepResult",
    "StopHitSweepService",
]
