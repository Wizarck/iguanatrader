"""On-demand ingestion service — fetches OpenBB + EDGAR facts inline.

Slice ``research-ad-hoc-mode`` (PR #214) wired the OpenBB sidecar.
Slice ``edgar-on-demand`` (this PR) adds SEC EDGAR XBRL filings so
tier-A growth features (``eps_growth_yoy`` / ``revenue_growth_yoy``)
populate on a brand-new symbol. Without EDGAR the growth pillar
scored 0.000 and the methodology downgraded the recommendation to
AVOID purely because of missing data — see PR #217 for the prompt
fix that softens AVOID → HOLD low-confidence; this PR closes the
data gap so the rating reflects real fundamentals.

The service is intentionally a thin orchestrator:

* It owns the policy of WHICH endpoints to call (OpenBB fundamentals
  + analyst ratings + ESG + 13-month historical prices; EDGAR XBRL
  filings for the past ``EDGAR_LOOKBACK_DAYS``).
* It does NOT decide WHEN to run (caller checks freshness / first-time
  flag and invokes accordingly).
* It does NOT touch ``symbol_universe`` — caller passes the resolved
  id from :func:`ensure_symbol_registered`.

Failure modes:

* Per-endpoint 4xx / 502 from OpenBB or per-filing parse errors from
  EDGAR are swallowed by the adapters and logged.
* Whole-source failures (EDGAR rate limit, sidecar unreachable) are
  caught at the service boundary so one source's outage doesn't kill
  the other's drafts.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import replace as dc_replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from iguanatrader.shared.time import now as utc_now

if TYPE_CHECKING:
    from iguanatrader.contexts.research.ports import ResearchFactDraft
    from iguanatrader.contexts.research.repository import ResearchRepository


class OpenBBSourceLike(Protocol):
    """Structural subset of :class:`OpenBBSidecarSource` we depend on.

    Lets tests inject a scripted fake without inheriting from the real
    adapter (which would drag in httpx / sidecar HTTP plumbing).
    """

    def fetch(self, symbol: str, since: datetime | None) -> Iterable[ResearchFactDraft]: ...

    def fetch_prices(
        self,
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterable[ResearchFactDraft]: ...


class EdgarSourceLike(Protocol):
    """Structural subset of :class:`SECEdgarSource` for the on-demand path.

    SEC EDGAR yields drafts for both filings (10-K / 10-Q metadata) and
    XBRL company facts (eps_diluted, revenues, …). The XBRL drafts are
    what tier-A providers consume to compute eps_growth_yoy /
    revenue_growth_yoy.
    """

    def fetch(self, symbol: str, since: datetime | None) -> Iterable[ResearchFactDraft]: ...


logger = logging.getLogger(__name__)

#: Historical price window the tier-A momentum provider needs. 13
#: months = ~273 trading days, enough for the 12-month return + a
#: month of slack so the relative-strength baseline isn't right at
#: the edge.
PRICE_WINDOW_DAYS = 395

#: EDGAR XBRL lookback window. ~2.5 years covers the last two annual
#: 10-K filings plus the most recent quarterly 10-Qs — enough to drive
#: every YoY computation tier-A needs without dragging the issuer's
#: full decade of history (which would inflate the fact table for one
#: refresh by 1000s of rows).
EDGAR_LOOKBACK_DAYS = 900


@dataclass(frozen=True, slots=True)
class IngestionOutcome:
    """Per-symbol ingestion summary returned to the caller.

    ``facts_inserted`` is the total across all sources;
    ``edgar_facts_inserted`` is broken out separately so the route
    layer can log whether the tier-A path got populated (a brief
    refresh with edgar_facts_inserted == 0 will still be partial).
    """

    facts_inserted: int
    endpoints_attempted: int
    edgar_facts_inserted: int = 0


class OnDemandIngestionService:
    """Inline ingestion (OpenBB sidecar + SEC EDGAR) for ad-hoc refresh."""

    def __init__(
        self,
        *,
        repository: ResearchRepository,
        openbb_source: OpenBBSourceLike,
        edgar_source: EdgarSourceLike | None = None,
    ) -> None:
        self._repo = repository
        self._source = openbb_source
        # EDGAR is optional: requires SEC_EDGAR_USER_AGENT env, and the
        # adapter raises ConfigError on construction if absent. The
        # route handler swallows that and passes None, so the service
        # degrades gracefully to OpenBB-only ingestion in dev/test.
        self._edgar = edgar_source

    async def ingest(
        self,
        *,
        symbol: str,
        symbol_universe_id: UUID,
    ) -> IngestionOutcome:
        """Run all configured sources for ``symbol`` and persist facts.

        Each draft is stamped with ``symbol_universe_id`` (the adapter
        emits it None) so the bitemporal row joins correctly back to
        the tenant's universe row created by
        :func:`ensure_symbol_registered`.
        """
        attempted = 0
        inserted = 0
        edgar_inserted = 0

        # OpenBB: fundamentals + analyst ratings + ESG.
        for draft in self._source.fetch(symbol, since=None):
            attempted += 1
            if await self._persist(draft, symbol_universe_id, symbol):
                inserted += 1

        # OpenBB: 13-month historical prices window.
        end = utc_now().date()
        start = end - timedelta(days=PRICE_WINDOW_DAYS)
        for draft in self._source.fetch_prices(
            symbol,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        ):
            attempted += 1
            if await self._persist(draft, symbol_universe_id, symbol):
                inserted += 1

        # SEC EDGAR: XBRL filings for the past ~2.5 years. Skipped when
        # the adapter isn't wired (dev/test, or SEC_EDGAR_USER_AGENT
        # unset in prod). Wrapped in a broad except so an EDGAR outage
        # doesn't kill the brief refresh — synthesis will just be
        # partial=true and the prompt's HOLD-low-confidence rule kicks
        # in (slice methodology-low-confidence).
        if self._edgar is not None:
            since = utc_now() - timedelta(days=EDGAR_LOOKBACK_DAYS)
            try:
                attempted += 1
                for draft in self._edgar.fetch(symbol, since=since):
                    if await self._persist(draft, symbol_universe_id, symbol):
                        inserted += 1
                        edgar_inserted += 1
            except Exception as exc:
                logger.warning(
                    "research.on_demand_ingestion.edgar_failed",
                    extra={"symbol": symbol, "error": str(exc)},
                )

        logger.info(
            "research.on_demand_ingestion.complete",
            extra={
                "symbol": symbol,
                "facts_inserted": inserted,
                "edgar_facts_inserted": edgar_inserted,
                "endpoints_attempted": attempted,
            },
        )
        return IngestionOutcome(
            facts_inserted=inserted,
            endpoints_attempted=attempted,
            edgar_facts_inserted=edgar_inserted,
        )

    async def _persist(
        self,
        draft: ResearchFactDraft,
        symbol_universe_id: UUID,
        symbol: str,
    ) -> bool:
        """Stamp + insert one draft; return True iff the row persisted.

        Wraps each insert in a ``session.begin_nested()`` SAVEPOINT so a
        UNIQUE-constraint violation (most commonly the partial unique
        index on ``(tenant_id, dedupe_key)``) rolls back just that one
        row instead of poisoning the entire ingestion batch. The
        ``refresh-always-reingests`` slice exposes the gap that the
        previous catch-and-log pattern hid: when ``newly_registered``
        was False the path was never exercised, so the duplicate-row
        handling was untested.
        """
        from iguanatrader.shared.contextvars import session_var

        stamped = dc_replace(draft, symbol_universe_id=symbol_universe_id)
        session = session_var.get()
        try:
            if session is not None:
                async with session.begin_nested():
                    await self._repo.insert_fact(stamped)
            else:  # pragma: no cover — tests inject explicit sessions
                await self._repo.insert_fact(stamped)
        except Exception as exc:
            logger.warning(
                "research.on_demand_ingestion.insert_failed",
                extra={
                    "symbol": symbol,
                    "fact_kind": draft.fact_kind,
                    "error": str(exc),
                },
            )
            return False
        return True


__all__ = [
    "EDGAR_LOOKBACK_DAYS",
    "PRICE_WINDOW_DAYS",
    "EdgarSourceLike",
    "IngestionOutcome",
    "OnDemandIngestionService",
    "OpenBBSourceLike",
]
