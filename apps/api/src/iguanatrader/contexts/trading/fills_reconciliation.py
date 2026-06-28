"""FillsReconciliationService — broker-fill drain, trade-close, equity snapshot.

Extracted from :class:`iguanatrader.contexts.trading.service.TradingService`
(which now delegates to it) to keep the fills/equity reconciliation path — a
cohesive, self-contained unit — out of the propose/execute orchestrator. The
logic is moved verbatim; behaviour is unchanged.

Responsibilities:

* :meth:`startup_reconcile` — boot-time catch-up window computation.
* :meth:`reconcile_fills_handler` — drain ``BrokerPort.reconcile_fills``,
  committing each fill at its unit-of-work boundary.
* :meth:`reconcile_one_fill` — process a single fill: dedup, persist,
  detect entry-vs-exit + terminal, close the trade + compute realised P&L +
  infer the exit reason on a native-bracket leg, publish ``TradeClosed`` /
  ``OrderFilled`` / ``EquityUpdated``, snapshot equity.
* :meth:`_compute_realised_pnl` — pure P&L calc over a trade's fills.

Collaborators: the in-process :class:`MessageBus` (event publish) and a
:class:`BrokerPort` (fill stream + account equity). Repositories are
constructed per-call / passed in, and the session is read from
``session_var`` via the repositories (the service never threads a session
through its call stack — slice-2 D2).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import structlog

from iguanatrader.contexts.trading.events import EquityUpdated, OrderFilled, TradeClosed
from iguanatrader.contexts.trading.models import EquitySnapshot, Fill, Trade
from iguanatrader.contexts.trading.repository import (
    EquitySnapshotRepository,
    FillRepository,
    OrderRepository,
    TradeRepository,
)
from iguanatrader.shared.contextvars import session_var, with_tenant_context
from iguanatrader.shared.time import now as utc_now

if TYPE_CHECKING:
    from iguanatrader.contexts.trading.ports import BrokerPort, FillEvent
    from iguanatrader.shared.messagebus import MessageBus

log = structlog.get_logger("iguanatrader.contexts.trading.fills_reconciliation")


class FillsReconciliationService:
    """Broker-fill drain + trade-close + equity-snapshot reconciler.

    Holds the same ``bus`` + ``broker`` collaborators the reconciliation
    bodies referenced when they lived on :class:`TradingService`.
    """

    def __init__(self, *, bus: MessageBus, broker: BrokerPort) -> None:
        self._bus = bus
        self._broker = broker

    # ------------------------------------------------------------------
    # Restart reconciliation (slice order-timeout-restart-reconcile)
    # ------------------------------------------------------------------
    async def startup_reconcile(
        self,
        *,
        safety_margin_minutes: int = 10,
    ) -> None:
        """Drain any broker fills the daemon missed while it was down.

        Called once from the composition root (CLI startup) before
        :meth:`register_subscriptions`. Computes a ``since`` timestamp
        as ``max(filled_at) - safety_margin_minutes`` across all fills
        in the DB; falls back to ``now - 24 h`` if the DB is empty.

        The safety margin compensates for clock skew + the
        worst-case window where the broker recorded a fill but the
        daemon crashed before persisting it. The reconcile is
        idempotent at the broker_fill_id level (
        :meth:`reconcile_one_fill` deduplicates), so a slightly-too-
        old ``since`` is preferable to a slightly-too-new one.
        """
        fill_repo = FillRepository()
        latest = await fill_repo.latest_filled_at()
        if latest is None:
            since = utc_now() - timedelta(hours=24)
            log.info(
                "trading.startup_reconcile.fallback_window",
                since=since.isoformat(),
                reason="no fills in DB yet",
            )
        else:
            since = latest - timedelta(minutes=safety_margin_minutes)
            log.info(
                "trading.startup_reconcile.computed_window",
                latest_fill_at=latest.isoformat(),
                since=since.isoformat(),
                safety_margin_minutes=safety_margin_minutes,
            )
        await self.reconcile_fills_handler(since)

    # ------------------------------------------------------------------
    # reconcile_fills_handler (drain broker fills)
    # ------------------------------------------------------------------
    async def reconcile_fills_handler(self, since: datetime) -> None:
        """On heartbeat tick / reconnect, drain ``BrokerPort.reconcile_fills(since)``.

        Persist each :class:`Fill`, update :class:`Trade.state` when the
        order is fully filled, publish :class:`OrderFilled`, and snapshot
        equity on terminal state.
        """
        log.info("trading.fills.reconcile.started", since=since.isoformat())
        fill_repo = FillRepository()
        order_repo = OrderRepository()
        trade_repo = TradeRepository()
        equity_repo = EquitySnapshotRepository()

        async for fill_event in self._broker.reconcile_fills(since):
            # Bind the fill's tenant so the append-only / tenant guard accepts
            # the fills/equity inserts. The reconcile runs at boot + on the
            # heartbeat, outside any request/bus tenant scope, so tenant_id_var
            # would otherwise be unset and the insert raises
            # TenantContextMismatchError (audit #33). Per-fill scope keeps each
            # write bound to its own tenant.
            async with with_tenant_context(fill_event.tenant_id):
                await self.reconcile_one_fill(
                    fill_event,
                    fill_repo=fill_repo,
                    order_repo=order_repo,
                    trade_repo=trade_repo,
                    equity_repo=equity_repo,
                )
                # Audit #2: commit each reconciled fill at its unit-of-work
                # boundary. The boot/heartbeat reconcile runs on a long-lived
                # session that is otherwise never committed, so without this the
                # fill (and any terminal close/equity write) is logged as
                # persisted but rolled back when the session closes — the
                # position never lands in the ledger.
                session = session_var.get(None)
                if session is not None:
                    await session.commit()
        log.info("trading.fills.reconcile.completed")

    async def reconcile_one_fill(
        self,
        fill_event: FillEvent,
        *,
        fill_repo: FillRepository,
        order_repo: OrderRepository,
        trade_repo: TradeRepository,
        equity_repo: EquitySnapshotRepository,
    ) -> None:
        """Process a single :class:`FillEvent` (slice T4 §2.C body)."""
        if fill_event.broker_fill_id and await fill_repo.exists_by_broker_fill_id(
            fill_event.broker_fill_id
        ):
            log.info(
                "trading.fill.dedup_skip",
                broker_fill_id=fill_event.broker_fill_id,
            )
            return

        # The broker echoes our ``order_ref`` (the deterministic
        # ``client_order_id``) on every fill, so resolve by that first — this
        # is what real IBKR executions carry. Fall back to the primary key for
        # call paths that reference an order by its id directly. Without the
        # client_order_id lookup, ``get_by_id`` is handed a client_order_id and
        # never matches, so genuine fills log ``order_missing`` and the position
        # is never recorded (the trade is left dangling open).
        order = await order_repo.get_by_client_order_id(
            fill_event.order_id
        ) or await order_repo.get_by_id(fill_event.order_id)
        if order is None:
            log.warning(
                "trading.fill.order_missing",
                order_id=str(fill_event.order_id),
                broker_fill_id=fill_event.broker_fill_id,
            )
            return

        fill_id = uuid4()
        fill = Fill(
            id=fill_id,
            tenant_id=fill_event.tenant_id,
            order_id=order.id,
            quantity_filled=fill_event.quantity_filled,
            fill_price=fill_event.fill_price,
            commission=fill_event.commission,
            commission_currency=fill_event.commission_currency,
            filled_at=fill_event.filled_at,
            broker_fill_id=fill_event.broker_fill_id,
        )
        await fill_repo.add(fill)

        total_filled = await fill_repo.sum_quantity_for_order(order.id)
        # `total_filled` already includes the just-added fill via the SUM.
        is_terminal = bool(Decimal(str(total_filled)) >= Decimal(str(order.quantity)))

        # Slice ``trade-close-flow-exit-pathway``: differentiate entry
        # vs exit fills by comparing the order's side to the trade's
        # side. An entry order has the same side as the trade (BUY for
        # a long); an exit order has the opposite (SELL for a long).
        # * Entry fill (terminal or partial): trade stays in
        #   ``state="open"`` (position is/becomes live; no state change).
        # * Exit fill terminal: transition trade to ``state="closed"``,
        #   stamp ``closed_at``, compute ``realised_pnl`` over all
        #   entry/exit fills.
        # * Exit fill partial: trade stays in ``state="closing"`` —
        #   ``close_trade`` already set that when the exit order was
        #   submitted; no state change here.
        trade = await trade_repo.get_by_id(order.trade_id)
        is_exit_fill = trade is not None and order.side != trade.side
        if is_exit_fill and is_terminal and trade is not None:
            realised_pnl = await self._compute_realised_pnl(
                trade=trade,
                fill_repo=fill_repo,
                order_repo=order_repo,
            )
            closed_at = utc_now()
            # A close via ``close_trade`` already stamped the trade's
            # ``exit_reason`` (stop/target/manual/expiry). A native-bracket leg
            # filling does NOT go through ``close_trade`` (the stop/target rest
            # at the broker), so the reason is still NULL here — infer it from
            # the filled leg so the journal records a stop-out as "stop", not a
            # misleading "manual".
            exit_reason = trade.exit_reason
            if exit_reason is None:
                exit_reason = "stop" if order.order_type == "stop" else "target"
            await trade_repo.update_state(
                trade.id,
                state="closed",
                closed_at=closed_at,
                realised_pnl=realised_pnl,
                exit_reason=exit_reason,
            )

            # Slice A3 — publish TradeClosed for the auto-journal
            # subscriber (and any future analytics consumers). Fire-and-
            # forget: a handler failure (LLM timeout, budget exceeded,
            # Hindsight retain network error) MUST NOT roll back this
            # close. Bus delivery itself is best-effort per the shared
            # messagebus contract.
            await self._bus.publish(
                TradeClosed(
                    tenant_id=trade.tenant_id,
                    trade_id=trade.id,
                    symbol=trade.symbol,
                    side=trade.side,
                    quantity=trade.quantity,
                    realised_pnl=realised_pnl,
                    exit_reason=str(exit_reason),
                    closed_at=closed_at,
                )
            )

        await self._bus.publish(
            OrderFilled(
                tenant_id=fill_event.tenant_id,
                order_id=order.id,
                fill_id=fill_id,
            )
        )
        log.info(
            "trading.fill.persisted",
            fill_id=str(fill_id),
            order_id=str(order.id),
            quantity_filled=str(fill_event.quantity_filled),
            fully_filled=is_terminal,
            is_exit_fill=is_exit_fill,
        )

        if is_terminal:
            equity_value = await self._broker.get_account_equity()
            snapshot_id = uuid4()
            snapshot = EquitySnapshot(
                id=snapshot_id,
                tenant_id=equity_value.tenant_id,
                mode=equity_value.mode,
                account_equity=equity_value.account_equity,
                cash_balance=equity_value.cash_balance,
                realized_pnl_today=equity_value.realized_pnl_today,
                unrealized_pnl=equity_value.unrealized_pnl,
                currency=equity_value.currency,
                snapshot_kind=equity_value.snapshot_kind,
            )
            await equity_repo.add(snapshot)
            await self._bus.publish(
                EquityUpdated(
                    tenant_id=equity_value.tenant_id,
                    equity_snapshot_id=snapshot_id,
                )
            )
            log.info(
                "trading.equity.snapshot_recorded",
                snapshot_id=str(snapshot_id),
                trade_id=str(order.trade_id),
                account_equity=str(equity_value.account_equity),
            )

    async def _compute_realised_pnl(
        self,
        *,
        trade: Trade,
        fill_repo: FillRepository,
        order_repo: OrderRepository,
    ) -> Decimal:
        """Compute realised P&L over the trade's full entry + exit fills.

        For a long (``trade.side == "buy"``):
        ``realised_pnl = exit_proceeds - entry_cost - commissions``
        where:
        * ``entry_cost = sum(fill.quantity * fill.price)`` over fills
          whose order shares the trade's side.
        * ``exit_proceeds = sum(fill.quantity * fill.price)`` over
          fills whose order has the opposite side.
        * ``commissions`` = total commission across all fills (both
          legs) — broker debits commission on each fill regardless of
          leg.

        For a short, the formula inverts: ``entry_proceeds -
        exit_cost - commissions`` (sold high to enter, bought low to
        exit).

        Returns ``Decimal("0")`` if the trade has no exit fills yet
        (shouldn't fire in production — the caller gates on
        ``is_exit_fill and is_terminal``).
        """
        all_orders = await order_repo.list_for_trade(trade.id)
        side_by_order: dict[UUID, str] = {o.id: o.side for o in all_orders}
        fills = await fill_repo.list_for_trade(trade.id)

        entry_value = Decimal("0")
        exit_value = Decimal("0")
        total_commission = Decimal("0")
        for fill in fills:
            order_side = side_by_order.get(fill.order_id)
            if order_side is None:
                # Defensive: orphan fill (shouldn't happen given FK).
                continue
            qty = Decimal(str(fill.quantity_filled))
            price = Decimal(str(fill.fill_price))
            commission = Decimal(str(fill.commission or 0))
            value = qty * price
            total_commission += commission
            if order_side == trade.side:
                entry_value += value
            else:
                exit_value += value

        if trade.side == "buy":
            return exit_value - entry_value - total_commission
        return entry_value - exit_value - total_commission


__all__ = ["FillsReconciliationService"]
