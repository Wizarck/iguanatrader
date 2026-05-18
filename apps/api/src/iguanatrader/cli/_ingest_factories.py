"""Per-adapter factories + persist closure for the I7 ingest scheduler.

Until this module landed, ``IngestSchedulerService.bootstrap_ingest_routines``
was called with ``sources={}`` from :func:`wire_llm_handlers` — the
scheduler registered jobs but had no adapters to invoke, so the I7
slice was decorative. This module builds the production source-factory
map and the ``persist_drafts`` bridge so the cron jobs actually ingest.

Design choices:

* **No-arg factories**: each entry is ``lambda: AdapterClass()``. Adapters
  read their secrets (API_KEY env vars, ScrapeLadder config, etc.) at
  construction. When an env var is missing the adapter raises
  :class:`ConfigError`, the scheduler's ``except Exception`` block
  swallows it, writes an ``IngestRun`` row with ``status='error'``, and
  moves on. Silent-skip-when-unconfigured is the intended behaviour —
  one operator wiring a single key should not fail unrelated jobs.
* **Watchlist projection**: the scheduler needs
  ``(tenant_id, symbol, symbol_universe_id, brief_refresh_*)`` per row,
  which requires a JOIN to ``symbol_universe`` since ``WatchlistConfig``
  only stores the FK. The loader runs once at bootstrap; per-tick
  scheduling is then purely in-memory on the APScheduler side.
* **persist_drafts closure**: stamps ``symbol_universe_id`` on each
  draft and inserts via :class:`ResearchRepository.insert_fact` inside
  a fresh session (the scheduler's per-tick callable cannot reuse the
  daemon's long-lived session — tenant_id_var must be re-bound per
  tick).

Source coverage at this slice:

* sec_edgar, fred, openbb-sidecar, ibkr, finnhub, motley-fool,
  edgartools — production adapters already used by the manual CLI.
* bea, bls, gdelt, openfda, vdem, wgi_world_bank — adapters built in
  R2/R3 but never given a CLI or scheduler wiring. Activating them
  here closes the orphan-source gap surfaced in the May 2026
  hidden-debt audit.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import replace as dc_replace
from typing import Any
from uuid import UUID

import sqlalchemy as sa

from iguanatrader.contexts.research.ingest_scheduler import (
    SourceFactory,
    WatchlistRow,
)
from iguanatrader.contexts.research.ports import ResearchFactDraft
from iguanatrader.contexts.research.repository import ResearchRepository
from iguanatrader.shared.contextvars import session_var

logger = logging.getLogger(__name__)


def build_source_factories() -> dict[str, SourceFactory]:
    """Return the production ``{source_id: factory}`` map.

    Each factory is the adapter's no-arg constructor: secrets are read
    from env at construction, so unconfigured adapters self-exclude by
    raising :class:`ConfigError` — caught by the scheduler's per-job
    try/except and counted as an error run instead of crashing the
    whole sweep.
    """
    # Lazy imports per gotcha #29 (CLI --help performance + composition
    # root keeps the bootstrap surface narrow). The factories themselves
    # incur the import cost only on first scheduler tick.

    def _sec_edgar() -> Any:
        from iguanatrader.contexts.research.sources.sec_edgar import SECEdgarSource

        return SECEdgarSource()

    def _fred() -> Any:
        from iguanatrader.contexts.research.sources.fred import FREDSource

        return FREDSource()

    def _openbb() -> Any:
        from iguanatrader.contexts.research.sources.openbb_sidecar import (
            OpenBBSidecarSource,
        )

        return OpenBBSidecarSource()

    def _ibkr() -> Any:
        from iguanatrader.contexts.research.sources.ibkr import IBKRSource

        return IBKRSource()

    def _finnhub() -> Any:
        from iguanatrader.contexts.research.sources.finnhub import FinnhubSource

        return FinnhubSource()

    def _motley_fool() -> Any:
        from iguanatrader.contexts.research.sources.motley_fool import (
            MotleyFoolTranscriptSource,
        )

        # Honours ENABLE_FOOL_SCRAPER env flag — raises ConfigError
        # when false, scheduler swallows + logs.
        return MotleyFoolTranscriptSource()

    def _edgartools() -> Any:
        from iguanatrader.contexts.research.sources.edgartools_narrative import (
            EdgartoolsSource,
        )

        return EdgartoolsSource()

    def _bea() -> Any:
        from iguanatrader.contexts.research.sources.bea import BEASource

        return BEASource()

    def _bls() -> Any:
        from iguanatrader.contexts.research.sources.bls import BLSSource

        return BLSSource()

    def _gdelt() -> Any:
        from iguanatrader.contexts.research.sources.gdelt import GDELTSource

        return GDELTSource()

    def _openfda() -> Any:
        from iguanatrader.contexts.research.sources.openfda import OpenFDASource

        return OpenFDASource()

    def _vdem() -> Any:
        from iguanatrader.contexts.research.sources.vdem import VDEMSource

        return VDEMSource()

    def _wgi() -> Any:
        from iguanatrader.contexts.research.sources.wgi_world_bank import WGISource

        return WGISource()

    return {
        "sec_edgar": _sec_edgar,
        "fred": _fred,
        "openbb-sidecar": _openbb,
        "ibkr": _ibkr,
        "finnhub": _finnhub,
        "motley-fool": _motley_fool,
        "edgartools": _edgartools,
        "bea": _bea,
        "bls": _bls,
        "gdelt": _gdelt,
        "openfda": _openfda,
        "vdem": _vdem,
        "wgi_world_bank": _wgi,
    }


def build_persist_drafts_closure(
    *,
    sessionmaker: Any,
) -> Callable[[Iterable[ResearchFactDraft], UUID], Awaitable[int]]:
    """Build the ``persist_drafts`` callable the scheduler invokes per job.

    The closure opens a fresh session per tick (the daemon's long-lived
    session cannot be shared across cron callbacks — APScheduler runs
    them on its own task), re-binds ``tenant_id_var`` from the draft's
    tenant, stamps ``symbol_universe_id`` on each draft, and inserts.
    """

    async def _persist(
        drafts: Iterable[ResearchFactDraft],
        symbol_universe_id: UUID,
    ) -> int:
        inserted = 0
        async with sessionmaker() as session:
            session_var.set(session)
            repo = ResearchRepository()
            for draft in drafts:
                # The scheduler's outer context binds tenant_id_var at
                # job-build time; the listener auto-stamps tenant_id on
                # INSERT so we only need to stamp the FK that the
                # adapter cannot know on its own.
                stamped = dc_replace(draft, symbol_universe_id=symbol_universe_id)
                try:
                    await repo.insert_fact(stamped)
                    inserted += 1
                except Exception as exc:
                    logger.warning(
                        "research.ingest.draft_failed",
                        extra={
                            "source_id": draft.source_id,
                            "symbol_universe_id": str(symbol_universe_id),
                            "error": f"{type(exc).__name__}: {exc}",
                        },
                    )
            await session.commit()
        return inserted

    return _persist


async def load_watchlist_for_ingest(*, sessionmaker: Any) -> list[WatchlistRow]:
    """Snapshot enabled :class:`WatchlistConfig` rows joined with their
    ``symbol_universe`` row so the scheduler has the ticker string.

    Read once at bootstrap. The scheduler does not need to react to
    runtime watchlist edits — a daemon restart picks up changes, same
    cadence as the other cron registrations.
    """
    from iguanatrader.contexts.research.models import SymbolUniverse, WatchlistConfig

    rows: list[WatchlistRow] = []
    async with sessionmaker() as session:
        # System-context read: the listener filters by tenant when
        # tenant_id_var is bound; for the cross-tenant snapshot we bind
        # nothing and rely on the explicit tenant_id column joined out.
        stmt = sa.select(
            WatchlistConfig.tenant_id,
            WatchlistConfig.symbol_universe_id,
            SymbolUniverse.symbol,
            WatchlistConfig.brief_refresh_schedule,
            WatchlistConfig.brief_refresh_cron,
            WatchlistConfig.enabled,
        ).join(
            SymbolUniverse,
            SymbolUniverse.id == WatchlistConfig.symbol_universe_id,
        )
        result = await session.execute(stmt)
        for row in result.all():
            tenant_id_raw, su_id_raw, symbol, schedule, cron, enabled = row
            tenant_id = (
                tenant_id_raw if isinstance(tenant_id_raw, UUID) else UUID(str(tenant_id_raw))
            )
            su_id = su_id_raw if isinstance(su_id_raw, UUID) else UUID(str(su_id_raw))
            rows.append(
                WatchlistRow(
                    tenant_id=tenant_id,
                    symbol_universe_id=su_id,
                    symbol=str(symbol),
                    brief_refresh_schedule=str(schedule),
                    brief_refresh_cron=cron,
                    enabled=bool(enabled),
                )
            )
    logger.info("research.ingest.watchlist_loaded", extra={"rows": len(rows)})
    return rows


__all__ = [
    "build_persist_drafts_closure",
    "build_source_factories",
    "load_watchlist_for_ingest",
]
