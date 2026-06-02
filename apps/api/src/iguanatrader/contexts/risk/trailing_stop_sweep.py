"""Trailing-stop sweep service — activates :func:`compute_trailing_stop`.

Slice ``orchestration-trailing-stops-cron``. PR #163 shipped the pure
function; this module adds the I/O layer that fetches open trades +
post-entry bars, calls the function per trade, and persists ratchet
events to ``trailing_stop_audit``.

The sweep is registered as a 6th cron job by
:meth:`OrchestrationService.bootstrap_routines` (every 15 minutes
during US market hours). Default-disabled inside :meth:`sweep` via the
``trail_trigger_pct is None`` check — matching the inert-by-construction
pattern used 4x elsewhere (stoploss_guard, cooldown_period, bollinger
squeeze, trailing_stops itself).

Per-trade failures (market-data fetch error, missing bars, etc.) are
caught + counted in ``trades_skipped_no_bars``; the sweep continues so
one bad symbol does not abort the rest. The whole-sweep duration is
measured for the operator dashboard.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from sqlalchemy import select

from iguanatrader.contexts.risk.models import RiskCaps
from iguanatrader.contexts.risk.stop_management import (
    TradeSnapshot,
    compute_trailing_stop,
)
from iguanatrader.contexts.risk.trailing_stop_repository import (
    TrailingStopAuditRepository,
)
from iguanatrader.contexts.trading.models import Trade, TradeProposal
from iguanatrader.contexts.trading.ports import MarketDataPort
from iguanatrader.shared.time import now as utc_now

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TrailingStopSweepResult:
    """Counters + duration returned from :meth:`TrailingStopSweepService.sweep`."""

    trades_evaluated: int
    trades_trailed: int
    trades_no_update: int
    trades_trigger_not_reached: int
    trades_skipped_no_bars: int
    duration_ms: int


class TrailingStopSweepService:
    """Per-tick orchestrator: open trades → :func:`compute_trailing_stop` → audit row.

    The service is stateless beyond its injected dependencies; the
    cron caller instantiates one per registration call and reuses it.
    """

    def __init__(
        self,
        *,
        session: AsyncSession | None = None,
        audit_repo: TrailingStopAuditRepository,
        risk_caps_provider: Callable[[], RiskCaps],
        market_data_port: MarketDataPort,
        clock: Callable[[], datetime] = utc_now,
        timeframe: str = "1d",
        lookback_bars: int = 200,
    ) -> None:
        # Audit #29: ``session`` is OPTIONAL. When omitted, the sweep resolves
        # the active session from ``session_var`` at call time so the cron
        # wrapper binds a FRESH per-tick session instead of riding the
        # long-lived ambient daemon session. Explicit callers (the integration
        # tests) keep passing one.
        self._explicit_session = session
        self._audit_repo = audit_repo
        self._risk_caps_provider = risk_caps_provider
        self._market_data_port = market_data_port
        self._clock = clock
        self._timeframe = timeframe
        self._lookback_bars = lookback_bars

    @property
    def _session(self) -> AsyncSession:
        if self._explicit_session is not None:
            return self._explicit_session
        from iguanatrader.shared.contextvars import session_var

        sess = session_var.get()
        if sess is None:
            raise LookupError(
                "TrailingStopSweepService has no session: pass session=... or "
                "bind session_var (per-tick cron scope)."
            )
        return cast("AsyncSession", sess)

    async def sweep(self) -> TrailingStopSweepResult:
        """Iterate open trades, compute trailing stops, persist ratchets."""
        started_at = self._clock()
        caps = self._risk_caps_provider()

        if caps.trail_trigger_pct is None:
            # Inert-by-config: no caps configured. Return a zero-result so
            # operator dashboards still see the sweep ran (vs. crashed).
            ended_at = self._clock()
            return TrailingStopSweepResult(
                trades_evaluated=0,
                trades_trailed=0,
                trades_no_update=0,
                trades_trigger_not_reached=0,
                trades_skipped_no_bars=0,
                duration_ms=int((ended_at - started_at).total_seconds() * 1000),
            )

        open_trades = await self._list_open_trades()

        trailed = 0
        no_update = 0
        trigger_not_reached = 0
        skipped = 0

        for trade in open_trades:
            try:
                outcome = await self._sweep_one(
                    trade=trade,
                    trail_trigger_pct=caps.trail_trigger_pct,
                    trail_atr_mult=caps.trail_atr_mult,
                    atr_period=caps.trail_atr_period,
                )
            except Exception as exc:
                logger.warning(
                    "risk.trailing_stop_sweep.symbol_failed: %s: %s",
                    type(exc).__name__,
                    exc,
                    extra={
                        "symbol": trade.symbol,
                        "trade_id": str(trade.id),
                    },
                )
                skipped += 1
                continue

            if outcome == "trailed":
                trailed += 1
            elif outcome == "no_update":
                no_update += 1
            else:
                trigger_not_reached += 1

        # Commit the audit rows accumulated during the per-trade loop.
        # The sweep is a transactional unit (one cron tick); without an
        # explicit commit the rows persist in the session's flush buffer
        # only, invisible to subsequent sessions / dashboards.
        if trailed > 0:
            await self._session.commit()

        ended_at = self._clock()
        duration_ms = int((ended_at - started_at).total_seconds() * 1000)

        logger.info(
            "risk.trailing_stop_sweep.completed",
            extra={
                "trades_evaluated": len(open_trades),
                "trades_trailed": trailed,
                "trades_no_update": no_update,
                "trades_trigger_not_reached": trigger_not_reached,
                "trades_skipped_no_bars": skipped,
                "duration_ms": duration_ms,
            },
        )

        return TrailingStopSweepResult(
            trades_evaluated=len(open_trades),
            trades_trailed=trailed,
            trades_no_update=no_update,
            trades_trigger_not_reached=trigger_not_reached,
            trades_skipped_no_bars=skipped,
            duration_ms=duration_ms,
        )

    async def _sweep_one(
        self,
        *,
        trade: Trade,
        trail_trigger_pct: Decimal,
        trail_atr_mult: Decimal,
        atr_period: int,
    ) -> str:
        """Process one trade. Returns the function's ``reason`` (after persist)."""
        entry_price, current_stop = await self._resolve_entry_and_stop(trade)
        bars = await self._market_data_port.get_bars(
            symbol=trade.symbol,
            timeframe=self._timeframe,  # type: ignore[arg-type]
            lookback_bars=self._lookback_bars,
        )

        # SQLite ``DateTime(timezone=True)`` round-trips as a naive
        # ``datetime`` (tz info is dropped). The pure function compares
        # ``b.timestamp > trade.opened_at`` so both sides must agree on
        # awareness; coerce naive values to UTC here at the I/O boundary.
        opened_at = trade.opened_at
        if opened_at.tzinfo is None:
            opened_at = opened_at.replace(tzinfo=UTC)

        snapshot = TradeSnapshot(
            trade_id=trade.id,
            side=trade.side,  # type: ignore[arg-type]
            entry_price=entry_price,
            stop_price=current_stop,
            opened_at=opened_at,
        )

        update = compute_trailing_stop(
            trade=snapshot,
            bars=bars,
            trail_trigger_pct=trail_trigger_pct,
            trail_atr_mult=trail_atr_mult,
            atr_period=atr_period,
        )

        if update.reason == "trailed":
            assert (
                update.atr is not None
            ), "trailed reason requires ATR per stop_management contract"
            await self._audit_repo.add_row(
                tenant_id=trade.tenant_id,
                trade_id=trade.id,
                swept_at=self._clock(),
                old_stop=update.old_stop,
                new_stop=update.new_stop,
                highest_close_since_entry=update.highest_close_since_entry,
                atr=update.atr,
                bars_evaluated=len(bars.bars),
            )

        return update.reason

    async def _list_open_trades(self) -> list[Trade]:
        """Fetch ``state == 'open'`` trades for the current tenant."""
        stmt = select(Trade).where(Trade.state == "open")
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _resolve_entry_and_stop(self, trade: Trade) -> tuple[Decimal, Decimal]:
        """Return ``(entry_price, current_stop)`` for ``trade``.

        Both values come from the trade's :class:`TradeProposal`:

        * ``entry_price`` is always ``TradeProposal.entry_price_indicative``
          (the ``Trade`` model itself does not carry an entry-price
          column — the proposal is the canonical source).
        * ``current_stop`` resolves to the latest
          ``trailing_stop_audit.new_stop`` for the trade if any audit
          row exists; otherwise falls back to ``TradeProposal.stop_price``.

        Raises :class:`ValueError` if the proposal row is absent — both
        columns are NOT NULL at the DB level, so this indicates a data-
        integrity issue rather than a default-handling case.
        """
        proposal_stmt = select(
            TradeProposal.entry_price_indicative,
            TradeProposal.stop_price,
        ).where(TradeProposal.id == trade.proposal_id)
        result = await self._session.execute(proposal_stmt)
        row = result.one_or_none()
        if row is None:
            raise ValueError(
                f"Cannot resolve entry/stop for trade {trade.id}: "
                f"proposal {trade.proposal_id} not found"
            )
        entry_price = Decimal(str(row[0]))
        proposal_stop = Decimal(str(row[1]))

        latest_audit = await self._audit_repo.get_latest_for_trade(trade.id)
        current_stop = (
            Decimal(str(latest_audit.new_stop)) if latest_audit is not None else proposal_stop
        )
        return entry_price, current_stop


__all__ = [
    "TrailingStopSweepResult",
    "TrailingStopSweepService",
]
