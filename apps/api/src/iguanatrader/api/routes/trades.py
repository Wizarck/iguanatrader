"""Trades read endpoints + close-flow trigger.

Read endpoints (slice ``trades-read-endpoints``): three GET endpoints
powered by :class:`TradeRepository` + :class:`FillRepository`. Tenant
scoping is automatic via the slice-3 ``tenant_listener``. Pagination
cursor returns ``None`` in v1; v2 SaaS slice adds it once trade volume
warrants.

Close-flow trigger (slice ``trade-close-flow-exit-pathway``):
``POST /trades/{id}/close`` publishes a :class:`CloseTradeRequested`
event on the in-process bus. The :class:`TradingService.close_trade_handler`
re-checks the state-machine gate (only ``state="open"`` trades are
closable) and submits the exit order.

The ``response_model=...`` declarations are intentional — they make
the canonical response shape visible in ``/openapi.json`` so the
slice-5 typegen pipeline emits the matching TypeScript interfaces in
``packages/shared-types/src/index.ts``.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.api.deps import get_current_user, get_db
from iguanatrader.api.dtos.trades import (
    CloseTradeIn,
    FillListOut,
    FillOut,
    OrderListOut,
    OrderOut,
    TradeJournalOut,
    TradeListOut,
    TradeOut,
)
from iguanatrader.contexts.research.synthesis.llm_client import (
    FakeLLMClient,
    LLMClient,
)
from iguanatrader.contexts.trading.events import CloseTradeRequested
from iguanatrader.contexts.trading.journaling import TradeJournalWriter
from iguanatrader.contexts.trading.repository import (
    FillRepository,
    OrderRepository,
    TradeRepository,
)
from iguanatrader.persistence import User
from iguanatrader.shared.contextvars import session_var
from iguanatrader.shared.errors import ConflictError, NotFoundError

log = structlog.get_logger("iguanatrader.api.routes.trades")

router = APIRouter(prefix="/trades", tags=["trades"])


@router.get("", response_model=TradeListOut)
async def list_trades(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TradeListOut:
    """List trades for the authenticated tenant (slice trades-read-endpoints)."""
    log.info("api.trades.list", tenant_id=str(user.tenant_id))
    session_var.set(db)
    repo = TradeRepository()
    rows = await repo.list_for_tenant()
    return TradeListOut(
        items=[TradeOut.model_validate(r) for r in rows],
        total=len(rows),
        next_cursor=None,
    )


@router.get("/{trade_id}", response_model=TradeOut)
async def get_trade(
    trade_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TradeOut:
    """Fetch a single trade by id (slice trades-read-endpoints)."""
    log.info("api.trades.get", trade_id=str(trade_id))
    session_var.set(db)
    repo = TradeRepository()
    row = await repo.get_by_id(trade_id)
    if row is None:
        raise NotFoundError(detail=f"Trade {trade_id} not found.")
    return TradeOut.model_validate(row)


@router.get("/{trade_id}/fills", response_model=FillListOut)
async def list_trade_fills(
    trade_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FillListOut:
    """List fills for a given trade (slice trades-read-endpoints).

    A trade with no fills yet returns an empty list (NOT 404) — the
    proposal could be approved + the order submitted but no broker
    execution yet. Empty list is the canonical in-flight response.
    """
    log.info("api.trades.fills", trade_id=str(trade_id))
    session_var.set(db)
    repo = FillRepository()
    rows = await repo.list_for_trade(trade_id)
    return FillListOut(
        items=[FillOut.model_validate(r) for r in rows],
        total=len(rows),
        next_cursor=None,
    )


@router.get("/{trade_id}/orders", response_model=OrderListOut)
async def list_trade_orders(
    trade_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderListOut:
    """List orders (entry + stop + target + exit) for a given trade.

    Slice ``u-next-2-trade-timeline``. The trade-detail page renders an
    Order timeline so operators can see whether the stop-loss + target
    have been accepted broker-side — today the only visible state is
    the trade-level ``state`` column, which collapses the four order
    rows into a single label. An empty list means the entry order has
    not yet been submitted (rare — usually only the brief window between
    ``ProposalApproved`` and ``broker.place_order`` returning).
    """
    log.info("api.trades.orders", trade_id=str(trade_id))
    session_var.set(db)
    repo = OrderRepository()
    rows = await repo.list_for_trade(trade_id)
    return OrderListOut(
        items=[OrderOut.model_validate(r) for r in rows],
        total=len(rows),
        next_cursor=None,
    )


@router.post("/{trade_id}/close", status_code=status.HTTP_202_ACCEPTED)
async def close_trade(
    trade_id: UUID,
    body: CloseTradeIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Operator-initiated close (slice ``trade-close-flow-exit-pathway``).

    Validates synchronously:
    * Trade exists for the authenticated tenant (else 404).
    * Trade is in ``state="open"`` (else 409 — ``closing`` means an
      exit is already pending, ``closed`` means terminated).

    Then publishes :class:`CloseTradeRequested` on the in-process bus.
    The :class:`TradingService.close_trade_handler` re-checks the gate
    (idempotency: bus-level dedupe on ``trade_id`` +
    :class:`TradeNotClosableError` defence inside the service), submits
    the exit order via the broker port, and writes
    ``state="closing"`` + ``exit_reason``. Terminal transition to
    ``state="closed"`` happens when the exit fill reconciles.

    Returns 202 Accepted — the broker submission is asynchronous; the
    trade lifecycle continues via the existing fill-reconcile path.
    """
    log.info(
        "api.trades.close",
        trade_id=str(trade_id),
        reason=body.reason,
        user_id=str(user.id),
    )
    session_var.set(db)

    repo = TradeRepository()
    trade = await repo.get_by_id(trade_id)
    if trade is None:
        raise NotFoundError(detail=f"Trade {trade_id} not found.")
    if trade.state != "open":
        raise ConflictError(
            detail=(
                f"Trade {trade_id} is in state={trade.state!r}; "
                "only 'open' trades can be closed."
            )
        )

    from iguanatrader.contexts.approval.bootstrap import get_message_bus

    bus = get_message_bus()
    await bus.publish(
        CloseTradeRequested(
            tenant_id=trade.tenant_id,
            trade_id=trade_id,
            reason=body.reason,
        )
    )
    log.info(
        "api.trades.close.published",
        trade_id=str(trade_id),
        reason=body.reason,
    )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"trade_id": str(trade_id), "reason": body.reason, "status": "submitted"},
    )


def _build_llm_client() -> LLMClient:
    """Pick the production or fake LLM client based on env.

    Mirrors the env gate used in proposals + research routes. Production
    env + populated ``ANTHROPIC_API_KEY`` swaps in the real adapter;
    dev / test envs stay on :class:`FakeLLMClient`.
    """
    env = (os.environ.get("IGUANATRADER_ENV") or "").strip().lower()
    if env in {"paper", "live", "production"} and os.environ.get("ANTHROPIC_API_KEY"):
        from iguanatrader.contexts.research.synthesis.anthropic_client import (
            build_anthropic_llm_client_from_env,
        )

        return build_anthropic_llm_client_from_env()
    return FakeLLMClient()


@router.post("/{trade_id}/journal", response_model=TradeJournalOut)
async def journal_trade(
    trade_id: UUID,
    regenerate: bool = Query(
        default=False,
        description="When true, regenerate the narrative even if one already exists.",
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TradeJournalOut:
    """LLM-generated post-mortem narrative for a closed trade.

    Persists ``narrative`` + ``model`` + ``generated_at`` on the trade
    row (migration 0018). Subsequent calls return the cached narrative
    via ``cached=true`` unless ``?regenerate=true`` is passed (which
    overwrites the existing narrative + bumps ``generated_at``).

    Returns 409 when the trade is not yet closed (``state != "closed"``)
    — there's no useful narrative for an open or closing position.
    Tagged ``application=iguanatrader-journal`` in Langfuse.
    """
    log.info(
        "api.trades.journal",
        trade_id=str(trade_id),
        regenerate=regenerate,
        tenant_id=str(user.tenant_id),
    )
    session_var.set(db)
    repo = TradeRepository()
    trade = await repo.get_by_id(trade_id)
    if trade is None:
        raise NotFoundError(detail=f"Trade {trade_id} not found.")
    if trade.state != "closed":
        raise ConflictError(
            detail=(
                f"Trade {trade_id} is in state={trade.state!r}; "
                "journal narrative requires a closed trade."
            )
        )

    # Return persisted narrative when present and the caller did not
    # opt in to a regenerate. This is the cheap path — zero LLM calls.
    if (
        not regenerate
        and trade.journal_narrative is not None
        and trade.journal_generated_at is not None
    ):
        return TradeJournalOut(
            trade_id=trade_id,
            narrative=trade.journal_narrative,
            model=trade.journal_model or "unknown",
            generated_at=trade.journal_generated_at,
            tokens_input=0,
            tokens_output=0,
            cached=True,
        )

    writer = TradeJournalWriter(_build_llm_client())
    result = await writer.write(
        trade_id=str(trade_id),
        symbol=trade.symbol,
        side=trade.side,
        quantity=trade.quantity,
        mode=trade.mode,
        opened_at=trade.opened_at,
        closed_at=trade.closed_at,
        exit_reason=trade.exit_reason,
        realised_pnl=trade.realised_pnl,
    )

    # Persist on the trade row. The mutable-columns whitelist for the
    # append-only listener includes these three columns (slice
    # ``llm-observability-and-signals`` extension).
    trade.journal_narrative = result.narrative
    trade.journal_generated_at = datetime.now(UTC)
    trade.journal_model = result.model
    await db.flush()

    return TradeJournalOut(
        trade_id=trade_id,
        narrative=result.narrative,
        model=result.model,
        generated_at=result.generated_at,
        tokens_input=result.tokens_input,
        tokens_output=result.tokens_output,
        cached=False,
    )


__all__ = ["router"]
