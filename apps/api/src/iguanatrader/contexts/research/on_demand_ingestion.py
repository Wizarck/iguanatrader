"""On-demand ingestion service — fetches OpenBB sidecar facts inline.

Slice ``research-ad-hoc-mode`` (2026-05-18). Wraps the existing
:class:`OpenBBSidecarSource` adapter so the brief-refresh route can
populate the bitemporal ``research_facts`` table the very first time
an operator researches an arbitrary symbol — instead of demanding
they SSH + run ``iguanatrader research ingest openbb <SYM>`` first.

The service is intentionally a thin orchestrator:

* It owns the policy of WHICH endpoints to call (fundamentals +
  analyst ratings + ESG + a 13-month historical-prices window).
* It does NOT decide WHEN to run (caller checks freshness / first-time
  flag and invokes accordingly).
* It does NOT touch ``symbol_universe`` — caller passes the resolved
  id from :func:`ensure_symbol_registered`.

Failure mode: per-endpoint 4xx / 502 errors are swallowed by the
sidecar adapter (logged as ``skipped_upstream_error``); other
:class:`IntegrationError` propagates so the route can surface a
useful problem+json without committing a half-ingested fact set.
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


logger = logging.getLogger(__name__)

#: Historical price window the tier-A momentum provider needs. 13
#: months = ~273 trading days, enough for the 12-month return + a
#: month of slack so the relative-strength baseline isn't right at
#: the edge.
PRICE_WINDOW_DAYS = 395


@dataclass(frozen=True, slots=True)
class IngestionOutcome:
    """Per-symbol ingestion summary returned to the caller."""

    facts_inserted: int
    endpoints_attempted: int


class OnDemandIngestionService:
    """Inline OpenBB ingestion for ad-hoc research refresh."""

    def __init__(
        self,
        *,
        repository: ResearchRepository,
        openbb_source: OpenBBSourceLike,
    ) -> None:
        self._repo = repository
        self._source = openbb_source

    async def ingest(
        self,
        *,
        symbol: str,
        symbol_universe_id: UUID,
    ) -> IngestionOutcome:
        """Run all OpenBB endpoints for ``symbol`` and persist facts.

        Each draft is stamped with ``symbol_universe_id`` (the adapter
        emits it None) so the bitemporal row joins correctly back to
        the tenant's universe row created by
        :func:`ensure_symbol_registered`.
        """
        attempted = 0
        inserted = 0

        # Endpoint 1-3: fundamentals + analyst ratings + ESG (one draft
        # each, ``fetch`` is a generator).
        for draft in self._source.fetch(symbol, since=None):
            attempted += 1
            stamped = dc_replace(draft, symbol_universe_id=symbol_universe_id)
            try:
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
                continue
            inserted += 1

        # Endpoint 4: historical prices window. Separate generator
        # because the sidecar route + payload shape are distinct.
        end = utc_now().date()
        start = end - timedelta(days=PRICE_WINDOW_DAYS)
        for draft in self._source.fetch_prices(
            symbol,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        ):
            attempted += 1
            stamped = dc_replace(draft, symbol_universe_id=symbol_universe_id)
            try:
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
                continue
            inserted += 1

        logger.info(
            "research.on_demand_ingestion.complete",
            extra={
                "symbol": symbol,
                "facts_inserted": inserted,
                "endpoints_attempted": attempted,
            },
        )
        return IngestionOutcome(
            facts_inserted=inserted,
            endpoints_attempted=attempted,
        )


__all__ = [
    "PRICE_WINDOW_DAYS",
    "IngestionOutcome",
    "OnDemandIngestionService",
]
