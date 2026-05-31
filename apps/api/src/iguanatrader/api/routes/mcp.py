"""iguanatrader-MCP read-only server scaffolding — slice B (final LLM slice).

Auto-discovered. Exposes a thin HTTP surface that Hermes (or any other
MCP-aware client) can consume conversationally over Telegram /
WhatsApp ("show me my last trade's journal", "what's the latest
brief on NVDA?"). This slice ships the scaffolding + three read-only
resources; a follow-up swaps the bespoke routes for full MCP
JSON-RPC compatibility once the upstream lib choice is locked
(`fastmcp` vs `mcp` SDK).

Surface (v1 — read-only only):

* ``GET /api/v1/mcp/trades/{trade_id}`` — trade row + journal
  narrative (if persisted; A3 auto-journal populates this).
* ``GET /api/v1/mcp/briefs/{symbol}/latest`` — most recent research
  brief for the symbol, body markdown included.
* ``GET /api/v1/mcp/portfolio`` — latest equity snapshot + open
  positions.

Auth:

* Shared static bearer token via env var ``IGUANATRADER_MCP_TOKEN``.
  Constant-time compare against the ``Authorization: Bearer <token>``
  header. No rotation, no JWT — this is a single-tenant trust
  envelope between iguanatrader and Hermes living on the same
  compose-network.
* Missing / unset env var → all routes return 503 (server not
  configured). Operators wire the token in
  ``/opt/iguanatrader/.env`` once they want MCP exposure.

Tenant resolution:

* Env var ``IGUANATRADER_MCP_TENANT_SLUG`` resolved once at first-
  request time; every MCP query runs inside ``with_tenant_context()``
  for that tenant. The slice-3 tenant listener auto-scopes the
  underlying queries; no per-route tenant gymnastics needed.

Out of scope for B (explicit):

* Action tools (``explain_proposal`` / ``risk_review`` / ``journal_trade``
  / ``synthesize_brief``) — they'd need to invoke the existing
  services + respect the A0 budget guard. Wired in a follow-up that
  also adds MCP JSON-RPC framing.
* Approve / reject / place_order — not exposed; the human-in-the-
  loop trust boundary is the approval-channels fanout (P1) which
  Hermes already participates in.
"""

from __future__ import annotations

import hmac
import os
from typing import Any, ClassVar
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, Path
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.api.deps import get_db
from iguanatrader.shared.contextvars import session_var, tenant_id_var
from iguanatrader.shared.errors import IguanaError

log = structlog.get_logger("iguanatrader.api.routes.mcp")

router = APIRouter(prefix="/mcp", tags=["mcp"])


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MCPNotConfiguredError(IguanaError):
    """Raised when the MCP token / tenant slug env vars are unset."""

    # #9: IguanaError renders the RFC 7807 problem from these ClassVars
    # (type_uri/default_title/default_status). The previous
    # ``status_code``/``code`` attributes were never read, so every MCP
    # error rendered as a generic 500 instead of 503/401/404.
    type_uri: ClassVar[str] = "urn:iguanatrader:error:mcp-not-configured"
    default_title: ClassVar[str] = "MCP Not Configured"
    default_status: ClassVar[int] = 503


class MCPUnauthorizedError(IguanaError):
    """Raised when the bearer token check fails."""

    type_uri: ClassVar[str] = "urn:iguanatrader:error:mcp-unauthorized"
    default_title: ClassVar[str] = "MCP Unauthorized"
    default_status: ClassVar[int] = 401


class MCPNotFoundError(IguanaError):
    """Raised when the requested resource doesn't exist for the
    configured tenant."""

    type_uri: ClassVar[str] = "urn:iguanatrader:error:mcp-not-found"
    default_title: ClassVar[str] = "MCP Not Found"
    default_status: ClassVar[int] = 404


# ---------------------------------------------------------------------------
# Auth + tenant resolution
# ---------------------------------------------------------------------------


_TOKEN_ENV = "IGUANATRADER_MCP_TOKEN"
_TENANT_ENV = "IGUANATRADER_MCP_TENANT_SLUG"


def _read_configured_token() -> str:
    token = os.environ.get(_TOKEN_ENV, "").strip()
    if not token:
        raise MCPNotConfiguredError(
            detail=(
                f"{_TOKEN_ENV} is unset. Generate a token, write it to "
                "/opt/iguanatrader/.env on the deployment host, and "
                "restart the api container. The same token belongs in "
                "eligia-core/mcp-servers.yaml (SOPS-encrypted)."
            )
        )
    return token


def _read_configured_tenant_slug() -> str:
    slug = os.environ.get(_TENANT_ENV, "").strip()
    if not slug:
        raise MCPNotConfiguredError(
            detail=f"{_TENANT_ENV} is unset; cannot resolve the MCP tenant context."
        )
    return slug


async def _bearer_auth(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    """FastAPI dependency that fails the request if the header doesn't
    match the configured token. Constant-time compare via ``hmac``.

    Returns None on success; raises :class:`MCPUnauthorizedError`
    otherwise (mapped to RFC 7807 401 by the global handler).
    """
    expected = _read_configured_token()  # raises MCPNotConfiguredError when unset

    if not authorization or not authorization.startswith("Bearer "):
        raise MCPUnauthorizedError(
            detail="Authorization header missing or not in 'Bearer <token>' shape."
        )
    presented = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8")):
        raise MCPUnauthorizedError(detail="MCP bearer token mismatch.")


async def _bind_tenant_context(db: AsyncSession = Depends(get_db)) -> None:
    """Resolve the configured tenant slug → tenant_id and bind both
    contextvars (``session_var`` + ``tenant_id_var``) for the request
    lifetime. Subsequent ORM queries are then auto-scoped by the
    slice-3 tenant listener.
    """
    from iguanatrader.persistence import Tenant

    # Tenant rows carry ``name`` not ``slug`` in this schema; the env
    # var name keeps the spec-friendly ``_SLUG`` label so operators
    # still recognise the contract from the LLM-features roadmap.
    slug = _read_configured_tenant_slug()
    stmt = select(Tenant).where(Tenant.name == slug)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise MCPNotConfiguredError(
            detail=f"Tenant {slug!r} not found in tenants table (matched on `name`)."
        )

    session_var.set(db)
    tenant_id_var.set(row.id)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class MCPTradeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    symbol: str
    side: str
    state: str
    realised_pnl: str | None
    journal_narrative: str | None
    closed_at: str | None


class MCPBriefResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    version: int
    methodology: str
    body_markdown: str
    created_at: str


class MCPPortfolioResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_equity: str
    cash_balance: str
    currency: str
    open_position_count: int
    as_of: str | None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/trades/{trade_id}",
    response_model=MCPTradeResponse,
    dependencies=[Depends(_bearer_auth), Depends(_bind_tenant_context)],
)
async def get_trade(
    trade_id: UUID = Path(..., description="The trade UUID."),
    db: AsyncSession = Depends(get_db),
) -> MCPTradeResponse:
    """Read a trade row + journal narrative."""
    from iguanatrader.contexts.trading.models import Trade

    trade = await db.get(Trade, trade_id)
    if trade is None:
        raise MCPNotFoundError(detail=f"trade {trade_id} not found")
    log.info("api.mcp.trade.get", trade_id=str(trade_id))
    return MCPTradeResponse(
        id=str(trade.id),
        symbol=trade.symbol,
        side=trade.side,
        state=trade.state,
        realised_pnl=str(trade.realised_pnl) if trade.realised_pnl is not None else None,
        journal_narrative=trade.journal_narrative,
        closed_at=trade.closed_at.isoformat() if trade.closed_at else None,
    )


@router.get(
    "/briefs/{symbol}/latest",
    response_model=MCPBriefResponse,
    dependencies=[Depends(_bearer_auth), Depends(_bind_tenant_context)],
)
async def get_latest_brief(
    symbol: str = Path(..., description="Ticker symbol (uppercase, e.g. NVDA)."),
    db: AsyncSession = Depends(get_db),
) -> MCPBriefResponse:
    """Return the latest brief for ``symbol`` in the configured tenant."""
    from iguanatrader.contexts.research.models import ResearchBrief, SymbolUniverse

    normalized = symbol.strip().upper()
    sym_row = (
        await db.execute(select(SymbolUniverse).where(SymbolUniverse.symbol == normalized))
    ).scalar_one_or_none()
    if sym_row is None:
        raise MCPNotFoundError(detail=f"symbol {normalized!r} not registered")

    brief_stmt = (
        select(ResearchBrief)
        .where(ResearchBrief.symbol_universe_id == sym_row.id)
        .order_by(ResearchBrief.version.desc())
        .limit(1)
    )
    brief = (await db.execute(brief_stmt)).scalar_one_or_none()
    if brief is None:
        raise MCPNotFoundError(detail=f"no brief yet for {normalized!r}")

    log.info("api.mcp.brief.get_latest", symbol=normalized, version=brief.version)
    return MCPBriefResponse(
        symbol=normalized,
        version=brief.version,
        methodology=brief.methodology,
        body_markdown=getattr(brief, "body_markdown", "") or getattr(brief, "thesis_text", ""),
        created_at=brief.created_at.isoformat(),
    )


@router.get(
    "/portfolio",
    response_model=MCPPortfolioResponse,
    dependencies=[Depends(_bearer_auth), Depends(_bind_tenant_context)],
)
async def get_portfolio(
    db: AsyncSession = Depends(get_db),
) -> MCPPortfolioResponse:
    """Return the latest equity snapshot + open position count."""
    from iguanatrader.contexts.trading.models import EquitySnapshot, Trade

    eq_stmt = select(EquitySnapshot).order_by(EquitySnapshot.id.desc()).limit(1)
    snapshot = (await db.execute(eq_stmt)).scalar_one_or_none()
    if snapshot is None:
        raise MCPNotFoundError(detail="no equity snapshot recorded yet")

    open_count_stmt = select(Trade).where(Trade.state == "open")
    open_count = len((await db.execute(open_count_stmt)).scalars().all())

    log.info("api.mcp.portfolio.get", open_count=open_count)
    return MCPPortfolioResponse(
        account_equity=str(snapshot.account_equity),
        cash_balance=str(snapshot.cash_balance),
        currency=snapshot.currency,
        open_position_count=open_count,
        as_of=_iso_or_none(getattr(snapshot, "snapshot_at", None)),
    )


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else None


__all__ = ["router"]
