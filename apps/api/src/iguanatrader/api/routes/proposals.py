"""Proposals routes — wired for list + get + manual-approve.

Endpoints:

* ``GET /proposals`` (slice ``proposals-list-endpoint``) — returns the
  :class:`ProposalListOut` for the authenticated tenant, ordered
  ``created_at DESC``.
* ``GET /proposals/{proposal_id}`` (T4 body fill) — returns the
  :class:`ProposalOut` projection.
* ``POST /proposals/{proposal_id}/approve`` (T4) — EXPLICIT break-glass
  operator override. Publishes :class:`ProposalApproved` directly, so it
  is guarded: requires ``?confirm=break-glass``, REFUSES while approvals
  are paused (``/lock``), and logs every use. The web dashboard uses the
  normal ``/approvals/{id}/approve`` path instead. slowapi-limited 5/min.

After slice ``proposals-list-endpoint`` shipped there are zero
remaining 501 stubs in the trading route surface.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.api.deps import get_current_user, get_db
from iguanatrader.api.dtos.proposals import (
    ProposalExplainOut,
    ProposalListOut,
    ProposalOut,
    ProposalRiskOut,
)
from iguanatrader.api.limiting import limiter
from iguanatrader.contexts.research.proposal_advisor import (
    ProposalExplainerService,
    ProposalRiskAssessor,
)
from iguanatrader.contexts.research.proposal_advisor.risk import (
    RiskAssessmentParseError,
)
from iguanatrader.contexts.research.synthesis.llm_client import (
    FakeLLMClient,
    LLMClient,
)
from iguanatrader.contexts.trading.events import ProposalApproved
from iguanatrader.contexts.trading.repository import (
    TradeProposalRepository,
    TradeRepository,
)
from iguanatrader.persistence import User
from iguanatrader.shared.contextvars import session_var
from iguanatrader.shared.errors import (
    ConflictError,
    IguanaError,
    NotFoundError,
    ValidationError,
)

log = structlog.get_logger("iguanatrader.api.routes.proposals")

router = APIRouter(prefix="/proposals", tags=["proposals"])


@router.get("", response_model=ProposalListOut)
async def list_proposals(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProposalListOut:
    """List proposals for the authenticated tenant (FR11)."""
    session_var.set(db)
    repo = TradeProposalRepository()
    rows = await repo.list_for_tenant()
    log.info(
        "api.proposals.list",
        tenant_id=str(user.tenant_id),
        count=len(rows),
    )
    return ProposalListOut(
        items=[ProposalOut.model_validate(r) for r in rows],
        total=len(rows),
        next_cursor=None,
    )


@router.get("/{proposal_id}", response_model=ProposalOut)
async def get_proposal(
    proposal_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProposalOut:
    """Fetch a single proposal by id (FR11; slice T4 §4.3)."""
    log.info("api.proposals.get", proposal_id=str(proposal_id))
    session_var.set(db)
    repo = TradeProposalRepository()
    proposal = await repo.get_by_id(proposal_id)
    if proposal is None:
        raise NotFoundError(detail=f"Proposal {proposal_id} not found.")
    return ProposalOut.model_validate(proposal)


@router.post("/{proposal_id}/approve", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("5/minute")
async def manual_approve(
    request: Request,
    proposal_id: UUID,
    confirm: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Break-glass operator-override approve (slice T4 §4.5; hardened).

    An EXPLICIT emergency override that bypasses the P1 channel flow and
    publishes :class:`ProposalApproved` directly. The web dashboard does
    NOT use it — it approves via ``/approvals/{id}/approve``, which runs
    the full pause + expiry + audit gates. Because the direct publish skips
    those gates, this path is guarded so it cannot become a silent bypass:

    * It must be invoked EXPLICITLY — ``?confirm=break-glass`` is required,
      so a generic client cannot trip an order through by accident.
    * It REFUSES while approvals are paused (``/lock`` active): a
      break-glass approve must not silently push a trade past the
      operator's pause. ``/unlock`` first, then retry. (The hard
      kill-switch is also re-checked downstream in
      ``execute_on_approval_handler``.)
    * Every use is logged at ``warning`` as ``api.proposals.break_glass_approve``
      for the operations audit trail.

    ``TradingService.execute_on_approval_handler`` re-checks idempotency
    via :class:`OrderRepository.get_by_proposal_id`, so a redundant call is
    a no-op. Rate-limited 5/min per (ip, user) compound key.
    """
    session_var.set(db)

    if confirm != "break-glass":
        raise ValidationError(
            detail=(
                "This endpoint is a break-glass operator override. Pass "
                "`?confirm=break-glass` to proceed, or use the normal approval "
                "path POST /api/v1/approvals/{request_id}/approve."
            )
        )

    repo = TradeProposalRepository()
    proposal = await repo.get_by_id(proposal_id)
    if proposal is None:
        raise NotFoundError(detail=f"Proposal {proposal_id} not found.")

    # Respect the operator pause (/lock). get_feature_flag is fail-safe
    # (returns the default, never raises) so a read failure does NOT wedge
    # the path — but a definitively paused tenant is refused.
    from iguanatrader.contexts.observability import tenant_admin

    paused = await tenant_admin.get_feature_flag(
        "approvals_paused", False, tenant_id=proposal.tenant_id
    )
    if paused:
        raise ConflictError(
            detail=(
                "Approvals are paused (/lock active); a break-glass approve "
                "will not bypass the pause. Run /unlock first, then retry."
            )
        )

    log.warning(
        "api.proposals.break_glass_approve",
        proposal_id=str(proposal_id),
        tenant_id=str(proposal.tenant_id),
        approved_by=str(user.id),
    )

    from iguanatrader.contexts.approval.bootstrap import get_message_bus

    bus = get_message_bus()
    await bus.publish(
        ProposalApproved(
            tenant_id=proposal.tenant_id,
            proposal_id=proposal_id,
            approved_by_user_id=user.id,
        )
    )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "proposal_id": str(proposal_id),
            "approved_by_user_id": str(user.id),
            "status": "queued",
            "via": "break-glass",
        },
    )


def _build_llm_client() -> LLMClient:
    """Pick the production or fake LLM client based on env.

    Mirrors the gate in ``api/routes/research.py``: production env +
    populated ``ANTHROPIC_API_KEY`` swaps in the real adapter; dev /
    test envs (and unset key) stay on :class:`FakeLLMClient`.
    """
    env = (os.environ.get("IGUANATRADER_ENV") or "").strip().lower()
    if env in {"paper", "live", "production"} and os.environ.get("ANTHROPIC_API_KEY"):
        from iguanatrader.contexts.research.synthesis.anthropic_client import (
            build_anthropic_llm_client_from_env,
        )

        return build_anthropic_llm_client_from_env()
    return FakeLLMClient()


class _RiskUpstreamParseError(IguanaError):
    """Surfaces a Risk Review LLM parse failure as RFC 7807 502 Bad Gateway."""

    type_uri = "urn:iguanatrader:error:risk-upstream-parse"
    default_title = "Risk Review Upstream Parse Failure"
    default_status = 502


@router.post("/{proposal_id}/explain", response_model=ProposalExplainOut)
@limiter.limit("10/minute")
async def explain_proposal(
    request: Request,
    proposal_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProposalExplainOut:
    """LLM-generated narrative for a proposal (slice ``llm-observability-and-signals``).

    Read-only — no DB mutation. Tagged
    ``application=iguanatrader-explainer`` in Langfuse.

    Rate-limited 10/min per (ip, user) compound key. The default is
    higher than ``manual_approve`` (5/min) because explainer calls are
    cheaper (haiku) and operators may bulk-review during a triage.
    """
    log.info(
        "api.proposals.explain",
        proposal_id=str(proposal_id),
        tenant_id=str(user.tenant_id),
    )
    session_var.set(db)
    repo = TradeProposalRepository()
    proposal = await repo.get_by_id(proposal_id)
    if proposal is None:
        raise NotFoundError(detail=f"Proposal {proposal_id} not found.")

    service = ProposalExplainerService(_build_llm_client())
    result = await service.explain(
        proposal_id=str(proposal_id),
        symbol=proposal.symbol,
        side=proposal.side,
        quantity=proposal.quantity,
        entry_price_indicative=proposal.entry_price_indicative,
        stop_price=proposal.stop_price,
        confidence_score=proposal.confidence_score,
        mode=proposal.mode,
        reasoning=proposal.reasoning,
    )
    return ProposalExplainOut(
        proposal_id=proposal_id,
        narrative=result.narrative,
        model=result.model,
        generated_at=result.generated_at,
        tokens_input=result.tokens_input,
        tokens_output=result.tokens_output,
    )


def _summarise_recent_trades(trades: Sequence[Any], limit: int = 10) -> str:
    """Render up to ``limit`` recent trades as a one-line summary string.

    Used as LLM context for the risk assessor. Output is intentionally
    terse so the prompt stays under 1500 tokens of context: per-trade
    fields are ``state``/``exit_reason``/``realised_pnl``.
    """
    from iguanatrader.contexts.trading.models import Trade

    closed: list[Trade] = [t for t in trades if isinstance(t, Trade) and t.state == "closed"][
        :limit
    ]
    if not closed:
        return "no closed trades in window"
    parts: list[str] = []
    wins = 0
    losses = 0
    for t in closed:
        pnl = t.realised_pnl
        if pnl is not None:
            if pnl > 0:
                wins += 1
            elif pnl < 0:
                losses += 1
        parts.append(
            f"{t.symbol} {t.side} pnl={pnl if pnl is not None else 'n/a'} "
            f"reason={t.exit_reason or 'n/a'}"
        )
    header = f"{len(closed)} closed (wins={wins}, losses={losses})"
    return header + "; " + " | ".join(parts)


@router.post("/{proposal_id}/risk-review", response_model=ProposalRiskOut)
@limiter.limit("5/minute")
async def risk_review_proposal(
    request: Request,
    proposal_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProposalRiskOut:
    """LLM-driven risk assessment (informational, does NOT block approval).

    Tagged ``application=iguanatrader-risk`` in Langfuse. Default model
    is sonnet (multi-attribute reasoning); the request is rate-limited
    5/min per (ip, user) because sonnet calls are ~10x the cost of
    haiku and the review is meant to be a one-shot gate, not bulk.

    Returns 502 ``urn:iguanatrader:error:risk-upstream-parse`` when the
    LLM produces a body that cannot be parsed into the expected JSON
    shape; the route otherwise propagates network / SDK errors via the
    global handler chain as 500s.
    """
    log.info(
        "api.proposals.risk_review",
        proposal_id=str(proposal_id),
        tenant_id=str(user.tenant_id),
    )
    session_var.set(db)
    proposal_repo = TradeProposalRepository()
    proposal = await proposal_repo.get_by_id(proposal_id)
    if proposal is None:
        raise NotFoundError(detail=f"Proposal {proposal_id} not found.")

    trade_repo = TradeRepository()
    recent_trades = await trade_repo.list_for_tenant()
    open_trades = await trade_repo.list_open_for_tenant()
    recent_summary = _summarise_recent_trades(recent_trades)

    service = ProposalRiskAssessor(_build_llm_client())
    try:
        result = await service.assess(
            proposal_id=str(proposal_id),
            symbol=proposal.symbol,
            side=proposal.side,
            quantity=proposal.quantity,
            entry_price_indicative=proposal.entry_price_indicative,
            stop_price=proposal.stop_price,
            confidence_score=proposal.confidence_score,
            mode=proposal.mode,
            reasoning=proposal.reasoning,
            recent_trades_summary=recent_summary,
            open_positions_count=len(open_trades),
        )
    except RiskAssessmentParseError as exc:
        raise _RiskUpstreamParseError(
            detail=f"Risk-review LLM returned an unparseable body: {exc}"
        ) from exc

    return ProposalRiskOut(
        proposal_id=proposal_id,
        risk_score=result.risk_score,
        flags=result.flags,
        rationale=result.rationale,
        model=result.model,
        generated_at=result.generated_at,
        tokens_input=result.tokens_input,
        tokens_output=result.tokens_output,
    )


__all__ = ["router"]
