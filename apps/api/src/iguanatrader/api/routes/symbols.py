"""Symbol search + discovery routes (slice U1).

Auto-discovered by :func:`iguanatrader.api.routes.register_routers`.
Powers the autocomplete dropdown on the research landing page.

Surface (v1 — tenant-scoped only):

* ``GET /api/v1/symbols/search?q=<prefix>&limit=10`` — prefix match
  against the caller's ``symbol_universe``. Returns up to ``limit``
  rows, ordered alphabetically by symbol. Empty/short ``q`` returns
  the first ``limit`` registered symbols (a "recent / popular"
  defaultable in a follow-up slice).

External discovery (NASDAQ / NYSE bundled snapshot per roadmap U1) is
deferred to a follow-up: with the ad-hoc auto-register flow shipped in
PR #214 a brand-new ticker still resolves on first ``/refresh``, so
the immediate UX gap is operator discoverability of THEIR existing
universe — which this route closes.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.api.deps import get_current_user, get_db
from iguanatrader.contexts.research.models import SymbolUniverse
from iguanatrader.persistence import User
from iguanatrader.shared.contextvars import session_var

log = structlog.get_logger("iguanatrader.api.routes.symbols")

router = APIRouter(prefix="/symbols", tags=["symbols"])


class SymbolMatch(BaseModel):
    """One autocomplete row.

    ``SymbolUniverse`` carries no long/short name today (the underlying
    schema only has symbol/exchange/sector/industry/market_cap_bucket).
    Until ``IBKRSource`` (I3) backfills the contract-details narrative,
    the ``name`` field surfaces a derived best-effort label —
    ``sector`` when present, falling back to ``exchange``. Operators
    typing ``"NV"`` see ``"NVDA · Semiconductors"`` instead of just
    ``"NVDA"``, which is enough to disambiguate similar tickers.
    """

    model_config = ConfigDict(extra="forbid")

    symbol: str
    name: str | None
    exchange: str | None
    sector: str | None
    industry: str | None
    registered: bool


@router.get("/search", response_model=list[SymbolMatch])
async def search_symbols(
    q: str = Query(default="", max_length=32, description="Symbol prefix (case-insensitive)."),
    limit: int = Query(default=10, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SymbolMatch]:
    """Prefix-match against the caller's tenant ``symbol_universe``."""
    log.info("api.symbols.search", q=q, limit=limit)
    session_var.set(db)

    normalized = q.strip().upper()
    stmt = select(SymbolUniverse).order_by(SymbolUniverse.symbol).limit(limit)
    if normalized:
        stmt = stmt.where(SymbolUniverse.symbol.like(f"{normalized}%"))

    rows = (await db.execute(stmt)).scalars().all()
    return [
        SymbolMatch(
            symbol=row.symbol,
            name=row.industry or row.sector or row.exchange,
            exchange=row.exchange,
            sector=row.sector,
            industry=row.industry,
            registered=True,
        )
        for row in rows
    ]


__all__ = ["router"]
