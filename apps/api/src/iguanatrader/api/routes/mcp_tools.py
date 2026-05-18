"""MCP action tools — slice ``mcp-action-tools``.

Adds four bearer-token-authed POST endpoints under
``/api/v1/mcp/tools/*`` that invoke the LLM-features keystone services
(A1 explainer, A2 risk-assessor, A3 journal writer, R5 brief
synthesizer) on demand. Pairs with the existing read-only routes in
``mcp.py`` so a Hermes / Telegram client can both query (existing) and
trigger (this slice) the same surface.

Out of scope (explicit):

* True MCP JSON-RPC 2.0 framing (``tools/list``, ``tools/call``,
  ``initialize`` handshake, SSE streaming). The official protocol
  requires a different envelope; adding it half-correctly is worse
  than the bespoke REST shape here. When Hermes consumes a full
  MCP-SDK client, the wrapper can adapt these endpoints into the
  protocol surface without touching the underlying handlers.
* Approve / reject / place_order tools — those cross the human-in-
  the-loop trust boundary and live behind the approval-channels
  fanout, not MCP. Documented in ``mcp.py``'s module docstring.

The shared bearer + tenant-context dependencies live in ``mcp.py`` and
are re-used here so a token works for both read-only and action paths.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.api.deps import get_db
from iguanatrader.api.routes.mcp import (
    MCPNotFoundError,
    _bearer_auth,
    _bind_tenant_context,
)

log = structlog.get_logger("iguanatrader.api.routes.mcp_tools")

router = APIRouter(prefix="/mcp/tools", tags=["mcp"])


# ---------------------------------------------------------------------------
# Tool registry — feeds ``GET /mcp/tools``
# ---------------------------------------------------------------------------


_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "explain_proposal",
        "description": (
            "Generate a 2-3 paragraph narrative for a proposal — feeds "
            "approval-channel messages."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "proposal_id": {"type": "string", "description": "UUID of the proposal."}
            },
            "required": ["proposal_id"],
        },
    },
    {
        "name": "risk_review",
        "description": (
            "Run an LLM risk review on a proposal. Returns structured " "risk-assessment output."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "proposal_id": {"type": "string", "description": "UUID of the proposal."}
            },
            "required": ["proposal_id"],
        },
    },
    {
        "name": "journal_trade",
        "description": (
            "Generate the post-mortem narrative for a closed trade. Persists to "
            "``trades.journal_narrative`` and (when Hindsight is wired) the recall "
            "bank."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "trade_id": {"type": "string", "description": "UUID of the trade."},
                "regenerate": {
                    "type": "boolean",
                    "description": (
                        "When true, overwrite an existing narrative. Default false "
                        "(returns the cached narrative if one exists)."
                    ),
                    "default": False,
                },
            },
            "required": ["trade_id"],
        },
    },
    {
        "name": "synthesize_brief",
        "description": (
            "Refresh the research brief for a symbol. Triggers ingestion + tier-A "
            "feature fetch + LLM synthesis + persist. Idempotent at "
            "``(symbol_universe_id, version)``."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol, e.g. NVDA."},
                "methodology": {
                    "type": "string",
                    "description": "One of three_pillar / canslim / magic_formula / qarp / multi_factor.",
                    "default": "three_pillar",
                },
            },
            "required": ["symbol"],
        },
    },
]


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class ToolSpecResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    input_schema: dict[str, Any]


class ToolListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tools: list[ToolSpecResponse]


class ExplainProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: UUID


class ExplainProposalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: UUID
    narrative: str


class RiskReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: UUID


class RiskReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: UUID
    risk_assessment: dict[str, Any]


class JournalTradeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trade_id: UUID
    regenerate: bool = False


class JournalTradeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trade_id: UUID
    narrative: str
    regenerated: bool


class SynthesizeBriefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    methodology: str = Field(default="three_pillar")


class SynthesizeBriefResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    brief_id: UUID
    version: int
    methodology: str
    partial: bool


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=ToolListResponse, dependencies=[Depends(_bearer_auth)])
async def list_tools() -> ToolListResponse:
    """Return the catalogue of MCP tools the server exposes.

    Hermes uses this to discover what it can ``invoke`` against. The
    shape mirrors the official MCP ``tools/list`` response (modulo the
    JSON-RPC envelope) so a future protocol upgrade is a thin
    wrapping layer rather than a redesign.
    """
    log.info("api.mcp.tools.list")
    return ToolListResponse(
        tools=[ToolSpecResponse(**spec) for spec in _TOOL_SPECS],
    )


@router.post(
    "/explain_proposal",
    response_model=ExplainProposalResponse,
    dependencies=[Depends(_bearer_auth), Depends(_bind_tenant_context)],
)
async def explain_proposal(
    body: ExplainProposalRequest,
    db: AsyncSession = Depends(get_db),
) -> ExplainProposalResponse:
    """Generate the proposal narrative on demand."""
    from iguanatrader.contexts.research.proposal_advisor.explainer import (
        ProposalExplainerService,
    )
    from iguanatrader.contexts.research.synthesis.anthropic_client import (
        build_anthropic_llm_client_from_env,
    )
    from iguanatrader.contexts.trading.models import TradeProposal

    proposal = await db.get(TradeProposal, body.proposal_id)
    if proposal is None:
        raise MCPNotFoundError(detail=f"proposal {body.proposal_id} not found")

    explainer = ProposalExplainerService(build_anthropic_llm_client_from_env())
    result = await explainer.explain(
        proposal_id=str(proposal.id),
        symbol=proposal.symbol,
        side=proposal.side,
        quantity=proposal.quantity,
        entry_price_indicative=proposal.entry_price_indicative,
        stop_price=proposal.stop_price,
        confidence_score=proposal.confidence_score,
        mode=proposal.mode,
        reasoning=proposal.reasoning or {},
    )
    log.info("api.mcp.tools.explain_proposal", proposal_id=str(body.proposal_id))
    return ExplainProposalResponse(
        proposal_id=body.proposal_id,
        narrative=result.narrative,
    )


@router.post(
    "/risk_review",
    response_model=RiskReviewResponse,
    dependencies=[Depends(_bearer_auth), Depends(_bind_tenant_context)],
)
async def risk_review(
    body: RiskReviewRequest,
    db: AsyncSession = Depends(get_db),
) -> RiskReviewResponse:
    """Run an LLM risk review on a proposal."""
    from iguanatrader.contexts.research.proposal_advisor.risk import (
        ProposalRiskAssessor,
    )
    from iguanatrader.contexts.research.synthesis.anthropic_client import (
        build_anthropic_llm_client_from_env,
    )
    from iguanatrader.contexts.trading.models import TradeProposal

    proposal = await db.get(TradeProposal, body.proposal_id)
    if proposal is None:
        raise MCPNotFoundError(detail=f"proposal {body.proposal_id} not found")

    assessor = ProposalRiskAssessor(build_anthropic_llm_client_from_env())
    assessment = await assessor.assess(
        proposal_id=str(proposal.id),
        symbol=proposal.symbol,
        side=proposal.side,
        quantity=proposal.quantity,
        entry_price_indicative=proposal.entry_price_indicative,
        stop_price=proposal.stop_price,
        confidence_score=proposal.confidence_score,
        mode=proposal.mode,
        reasoning=proposal.reasoning or {},
        # Recent-trades summary + open-position count would normally
        # be looked up from the trades repo; for the MCP-tool path we
        # pass empty defaults so the call works on a fresh tenant. The
        # auto-risk-review handler (A2) does the same when invoked via
        # bus events.
        recent_trades_summary="",
        open_positions_count=0,
    )
    log.info("api.mcp.tools.risk_review", proposal_id=str(body.proposal_id))
    return RiskReviewResponse(
        proposal_id=body.proposal_id,
        risk_assessment={
            "risk_score": assessment.risk_score,
            "flags": list(assessment.flags),
            "rationale": assessment.rationale,
        },
    )


@router.post(
    "/journal_trade",
    response_model=JournalTradeResponse,
    dependencies=[Depends(_bearer_auth), Depends(_bind_tenant_context)],
)
async def journal_trade(
    body: JournalTradeRequest,
    db: AsyncSession = Depends(get_db),
) -> JournalTradeResponse:
    """Generate the post-mortem journal narrative for a closed trade."""
    from iguanatrader.contexts.research.synthesis.anthropic_client import (
        build_anthropic_llm_client_from_env,
    )
    from iguanatrader.contexts.trading.journaling import TradeJournalWriter
    from iguanatrader.contexts.trading.models import Trade

    trade = await db.get(Trade, body.trade_id)
    if trade is None:
        raise MCPNotFoundError(detail=f"trade {body.trade_id} not found")

    if trade.journal_narrative and not body.regenerate:
        log.info("api.mcp.tools.journal_trade.cached", trade_id=str(body.trade_id))
        return JournalTradeResponse(
            trade_id=body.trade_id,
            narrative=str(trade.journal_narrative),
            regenerated=False,
        )

    writer = TradeJournalWriter(build_anthropic_llm_client_from_env())
    result = await writer.write(
        trade_id=str(trade.id),
        symbol=trade.symbol,
        side=trade.side,
        quantity=trade.quantity,
        mode=trade.mode,
        opened_at=trade.opened_at,
        closed_at=trade.closed_at,
        exit_reason=trade.exit_reason,
        realised_pnl=Decimal(str(trade.realised_pnl)) if trade.realised_pnl is not None else None,
    )
    trade.journal_narrative = result.narrative
    await db.commit()

    log.info(
        "api.mcp.tools.journal_trade.written",
        trade_id=str(body.trade_id),
        regenerate=body.regenerate,
    )
    return JournalTradeResponse(
        trade_id=body.trade_id,
        narrative=result.narrative,
        regenerated=True,
    )


@router.post(
    "/synthesize_brief",
    response_model=SynthesizeBriefResponse,
    dependencies=[Depends(_bearer_auth), Depends(_bind_tenant_context)],
)
async def synthesize_brief(
    body: SynthesizeBriefRequest,
    db: AsyncSession = Depends(get_db),
) -> SynthesizeBriefResponse:
    """Refresh the research brief for ``symbol``.

    Delegates to the same :class:`BriefService` path the manual
    ``/research/briefs/{symbol}/refresh`` route uses. Idempotent and
    safe to invoke repeatedly — the SAVEPOINT-per-fact behaviour in
    :class:`OnDemandIngestionService._persist` (slice #250) prevents
    duplicate inserts from poisoning the batch.
    """
    from iguanatrader.api.routes.research import _build_service
    from iguanatrader.contexts.research.repository import ResearchRepository

    repo = ResearchRepository()
    service = _build_service(repo)
    outcome = await service.refresh(
        symbol=body.symbol.strip().upper(),
        methodology=body.methodology,
    )
    await db.commit()
    log.info(
        "api.mcp.tools.synthesize_brief",
        symbol=body.symbol,
        version=outcome.brief.version,
        partial=outcome.brief.partial,
    )
    return SynthesizeBriefResponse(
        symbol=body.symbol.strip().upper(),
        brief_id=outcome.brief.id,
        version=outcome.brief.version,
        methodology=body.methodology,
        partial=outcome.brief.partial,
    )


__all__ = ["router"]
