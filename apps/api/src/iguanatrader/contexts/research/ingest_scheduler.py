# ruff: noqa: RUF002
"""Research-ingest scheduler (slice I7) — automates ingestion sources.

Per ingestion-wave roadmap §I7: registers cron jobs into the existing
:class:`APSchedulerAdapter` so adapters built in I0–I6 (sec-edgar,
fred, openbb, ibkr, finnhub, motley-fool, edgartools-narrative) run on
the cadence declared by each tenant's
``watchlist_configs.brief_refresh_schedule`` column instead of waiting
for a manual CLI invocation.

Design:

* **Pluggable source factory** — the service does NOT import each
  adapter directly. Callers pass a ``{source_id: SourceFactory}``
  mapping where ``SourceFactory`` is a callable returning the adapter
  instance. Production composition root supplies the real factories;
  tests pass fakes.
* **Schedule mapping** — ``brief_refresh_schedule`` values map to
  APScheduler cron kwargs:

  ============= =====================================================
   schedule     cron kwargs
  ============= =====================================================
   daily        ``hour=6, minute=0``               (06:00 UTC)
   weekly       ``day_of_week='mon', hour=6``      (Mon 06:00 UTC)
   manual       skipped — no auto-trigger
  ============= =====================================================

  Tenants needing finer control set ``brief_refresh_cron`` (free-form
  cron expr) which overrides the canonical mapping.
* **Run accounting** — each job invocation writes one ``IngestRun``
  row at start (status='started') and updates it on completion
  (status='ok' / 'error', facts_inserted, error_detail, finished_at).
  ``GET /api/v1/admin/ingest-runs`` consumes this history.
* **Failure isolation** — a job failure logs ``research.ingest.failed``
  + writes the error row, but does NOT abort the scheduler. Other
  jobs continue on their own schedules.

The service does NOT auto-start a process-wide scheduler. The
production composition root calls :meth:`bootstrap_ingest_routines`
after constructing the shared :class:`APSchedulerAdapter`; the same
adapter is then started by ``OrchestrationService.bootstrap_routines``
or the FastAPI lifespan.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from iguanatrader.contexts.research.ports import ResearchFactDraft
from iguanatrader.shared.time import now as utc_now

logger = logging.getLogger(__name__)


#: Maps ``WatchlistConfig.brief_refresh_schedule`` → APScheduler cron kwargs.
_SCHEDULE_TO_CRON: dict[str, dict[str, Any]] = {
    "daily": {"hour": 6, "minute": 0},
    "weekly": {"day_of_week": "mon", "hour": 6, "minute": 0},
}


@dataclass(frozen=True, slots=True)
class IngestJobSpec:
    """Description of one scheduled ingestion job.

    Composition root builds these per (config, source_id) pair and
    hands them to the scheduler.
    """

    name: str
    cron_kwargs: dict[str, Any]
    source_id: str
    symbol: str | None
    symbol_universe_id: UUID | None
    tenant_id: UUID
    fn: Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class WatchlistRow:
    """Minimal projection of ``WatchlistConfig`` the scheduler needs."""

    tenant_id: UUID
    symbol_universe_id: UUID
    symbol: str
    brief_refresh_schedule: str
    brief_refresh_cron: str | None
    enabled: bool


#: A source factory returns an adapter for a given source_id. The
#: adapter MUST expose either ``fetch_async(symbol, ...)`` (preferred)
#: or the sync ``fetch(symbol, since)`` SourcePort method. The service
#: probes for fetch_async first and falls back to sync fetch.
SourceFactory = Callable[[], Any]


class IngestRunRecorder:
    """Writes ``IngestRun`` rows. Pure plumbing — separated from the
    scheduler service so tests can verify the recorder contract
    without a live scheduler.

    Production composition: pass a callable taking an async session.
    Tests: pass a fake that buffers rows in-memory.
    """

    def __init__(
        self,
        session_provider: Callable[[], Any],
    ) -> None:
        self._session_provider = session_provider

    async def record_start(
        self,
        *,
        tenant_id: UUID,
        source_id: str,
        symbol: str | None,
        symbol_universe_id: UUID | None,
        invoked_by: str,
    ) -> UUID:
        run_id = uuid4()
        async with self._session_provider() as session:
            from iguanatrader.contexts.research.models import IngestRun

            row = IngestRun(
                id=run_id,
                tenant_id=tenant_id,
                source_id=source_id,
                symbol=symbol,
                symbol_universe_id=symbol_universe_id,
                invoked_by=invoked_by,
                status="started",
                facts_inserted=0,
                started_at=utc_now(),
            )
            session.add(row)
            await session.commit()
        return run_id

    async def record_finish(
        self,
        *,
        run_id: UUID,
        facts_inserted: int,
        error_detail: str | None = None,
    ) -> None:
        async with self._session_provider() as session:
            import sqlalchemy as sa

            from iguanatrader.contexts.research.models import IngestRun

            stmt = (
                sa.update(IngestRun)
                .where(IngestRun.id == run_id)
                .values(
                    status="ok" if error_detail is None else "error",
                    facts_inserted=facts_inserted,
                    error_detail=error_detail,
                    finished_at=utc_now(),
                )
            )
            await session.execute(stmt)
            await session.commit()


class IngestSchedulerService:
    """Registers ingest jobs into the APScheduler adapter.

    See module docstring for design + schedule mapping. The service is
    construction-only; jobs run on the scheduler's clock once
    :meth:`bootstrap_ingest_routines` returns.
    """

    def __init__(
        self,
        *,
        recorder: IngestRunRecorder,
        invoked_by: str = "ingest-scheduler",
    ) -> None:
        self._recorder = recorder
        self._invoked_by = invoked_by

    # ------------------------------------------------------------------
    # Job spec construction
    # ------------------------------------------------------------------

    def build_specs(
        self,
        *,
        watchlist: Iterable[WatchlistRow],
        sources: dict[str, SourceFactory],
        persist_drafts: Callable[[Iterable[ResearchFactDraft], UUID], Awaitable[int]],
    ) -> list[IngestJobSpec]:
        """Build one JobSpec per (watchlist row, source_id) pair.

        ``persist_drafts`` is the bridge to :class:`ResearchRepository`
        — composition root passes a closure that opens a session, calls
        ``repo.insert_fact()`` for each draft, and returns the count.
        Stays out of this service so the scheduler stays DB-agnostic.
        """
        specs: list[IngestJobSpec] = []
        for row in watchlist:
            if not row.enabled:
                continue
            cron_kwargs = _resolve_cron_kwargs(row)
            if cron_kwargs is None:
                continue  # manual schedule — no auto-trigger
            for source_id, factory in sources.items():
                specs.append(
                    self._build_one_spec(
                        row=row,
                        source_id=source_id,
                        factory=factory,
                        cron_kwargs=cron_kwargs,
                        persist_drafts=persist_drafts,
                    )
                )
        return specs

    def _build_one_spec(
        self,
        *,
        row: WatchlistRow,
        source_id: str,
        factory: SourceFactory,
        cron_kwargs: dict[str, Any],
        persist_drafts: Callable[[Iterable[ResearchFactDraft], UUID], Awaitable[int]],
    ) -> IngestJobSpec:
        name = f"research_ingest::{source_id}::{row.symbol}::{row.tenant_id}"
        recorder = self._recorder
        invoked_by = self._invoked_by

        async def _run() -> None:
            run_id = await recorder.record_start(
                tenant_id=row.tenant_id,
                source_id=source_id,
                symbol=row.symbol,
                symbol_universe_id=row.symbol_universe_id,
                invoked_by=invoked_by,
            )
            error: str | None = None
            inserted = 0
            try:
                adapter = factory()
                drafts = await _invoke_adapter(adapter, row.symbol)
                inserted = await persist_drafts(drafts, row.symbol_universe_id)
            except Exception as exc:  # log + record + don't crash scheduler
                error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "research.ingest.failed",
                    extra={
                        "source_id": source_id,
                        "symbol": row.symbol,
                        "tenant_id": str(row.tenant_id),
                        "error": error,
                    },
                )
            finally:
                await recorder.record_finish(
                    run_id=run_id,
                    facts_inserted=inserted,
                    error_detail=error,
                )

        return IngestJobSpec(
            name=name,
            cron_kwargs=cron_kwargs,
            source_id=source_id,
            symbol=row.symbol,
            symbol_universe_id=row.symbol_universe_id,
            tenant_id=row.tenant_id,
            fn=_run,
        )

    # ------------------------------------------------------------------
    # Bootstrap into APScheduler
    # ------------------------------------------------------------------

    def bootstrap_ingest_routines(
        self,
        *,
        scheduler: Any,
        watchlist: Iterable[WatchlistRow],
        sources: dict[str, SourceFactory],
        persist_drafts: Callable[[Iterable[ResearchFactDraft], UUID], Awaitable[int]],
    ) -> list[IngestJobSpec]:
        """Build + register jobs into ``scheduler`` (APScheduler adapter).

        Returns the list of specs so the caller can log a summary.
        """
        from iguanatrader.contexts.orchestration.scheduler import JobSpec

        specs = self.build_specs(
            watchlist=watchlist,
            sources=sources,
            persist_drafts=persist_drafts,
        )
        for spec in specs:
            job = JobSpec(name=spec.name, fn=spec.fn, cron_kwargs=spec.cron_kwargs)
            scheduler.add_job(job)
        logger.info(
            "research.ingest.bootstrap",
            extra={"jobs_registered": len(specs)},
        )
        return specs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_cron_kwargs(row: WatchlistRow) -> dict[str, Any] | None:
    """Map a watchlist row's schedule preference to APScheduler kwargs.

    Precedence: ``brief_refresh_cron`` (free-form override) wins over
    the canonical mapping; ``'manual'`` returns ``None`` so the
    scheduler skips the row.
    """
    if row.brief_refresh_cron:
        # Free-form cron strings come in unparsed; APScheduler accepts
        # them via ``CronTrigger.from_crontab()`` but our JobSpec uses
        # kwargs only — so we wire the raw expression through a single
        # `crontab` field that the adapter routes correctly.
        return {"crontab": row.brief_refresh_cron}
    schedule = (row.brief_refresh_schedule or "").lower()
    return _SCHEDULE_TO_CRON.get(schedule)


async def _invoke_adapter(adapter: Any, symbol: str) -> list[ResearchFactDraft]:
    """Probe the adapter surface — ``fetch_async`` first, then sync."""
    fetch_async = getattr(adapter, "fetch_async", None)
    if callable(fetch_async):
        result = await fetch_async(symbol)
        if isinstance(result, list):
            return result
        return list(result)
    sync_fetch = getattr(adapter, "fetch", None)
    if callable(sync_fetch):
        return list(sync_fetch(symbol, None))
    raise TypeError(
        f"Source {adapter!r} exposes neither fetch_async nor fetch — "
        "cannot schedule for ingestion."
    )


__all__ = [
    "IngestJobSpec",
    "IngestRunRecorder",
    "IngestSchedulerService",
    "SourceFactory",
    "WatchlistRow",
]
