# mypy: disable-error-code="no-any-unimported"
"""Production :class:`SchedulerProtocol` adapter wrapping APScheduler.

Resolves the deferred-install carry-forward from slice O2: the
:class:`InMemoryScheduler` fake stays for tests; production composition
root constructs this adapter and registers cron jobs via
:meth:`OrchestrationService.bootstrap_routines`.

Jobstore: ``MemoryJobStore``. The routines are registered as *bound
methods* of in-memory daemon services (via
:meth:`OrchestrationService.bootstrap_routines`), which a persistent
(pickling) jobstore cannot serialize. Persistence buys nothing here
anyway — the daemon re-runs ``bootstrap_routines`` on every boot, so
the full cron schedule is rebuilt from code each start; a deploy-missed
daily run is re-armed by its cron trigger on the next process start.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import structlog

from iguanatrader.contexts.orchestration.scheduler import JobSpec

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler


log = structlog.get_logger("iguanatrader.contexts.orchestration.apscheduler_adapter")

_DEFAULT_TIMEZONE = ZoneInfo("America/New_York")
_DEFAULT_MISFIRE_GRACE_SECONDS = 300
#: How often the wakeup watchdog re-pokes the scheduler (see ``start``). Must be
#: well under the tightest cron interval (the minute sweeps) so a due job never
#: waits more than this for ``_process_jobs`` to run.
_WAKEUP_WATCHDOG_SECONDS = 20


class APSchedulerAdapter:
    """Production :class:`SchedulerProtocol` — ``AsyncIOScheduler`` shim."""

    def __init__(
        self,
        *,
        jobstore_url: str,
        timezone: ZoneInfo | None = None,
        scheduler: AsyncIOScheduler | None = None,
    ) -> None:
        self._jobstore_url = jobstore_url
        self._timezone = timezone or _DEFAULT_TIMEZONE
        self._scheduler: AsyncIOScheduler | None = scheduler
        self._registered: dict[str, JobSpec] = {}
        self._watchdog_task: asyncio.Task[None] | None = None

    def _ensure(self) -> AsyncIOScheduler:
        if self._scheduler is None:
            from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED
            from apscheduler.jobstores.memory import MemoryJobStore
            from apscheduler.schedulers.asyncio import AsyncIOScheduler

            # MemoryJobStore, not SQLAlchemyJobStore: the routines are bound
            # methods of in-memory daemon services, which a persistent
            # jobstore cannot pickle ("This Job cannot be serialized since
            # the reference to its callable could not be determined") — it
            # crash-looped the full-mode daemon at scheduler.start(). The
            # daemon rebuilds the schedule from code on every boot, so the
            # ``_jobstore_url`` (kept for constructor/back-compat) is unused.
            self._scheduler = AsyncIOScheduler(
                jobstores={"default": MemoryJobStore()},
                timezone=self._timezone,
                job_defaults={
                    "misfire_grace_time": _DEFAULT_MISFIRE_GRACE_SECONDS,
                    # #21: keep ``max_instances=1`` — the daemon shares a
                    # single AsyncSession (#29), so two overlapping runs of
                    # the same job would corrupt each other's pending state.
                    # ``coalesce`` collapses a backlog of missed ticks into
                    # one catch-up run instead of a thundering herd.
                    "max_instances": 1,
                    "coalesce": True,
                },
            )
            # #21: a run skipped because the previous one was still going
            # (or one that raised) used to vanish silently. Surface both so
            # an operator sees a sweep that is consistently overrunning its
            # interval.
            self._scheduler.add_listener(self._on_job_missed, EVENT_JOB_MISSED)
            self._scheduler.add_listener(self._on_job_error, EVENT_JOB_ERROR)
        return self._scheduler

    @staticmethod
    def _on_job_missed(event: Any) -> None:
        log.warning(
            "orchestration.scheduler.job_missed",
            job_id=getattr(event, "job_id", None),
            scheduled_run_time=str(getattr(event, "scheduled_run_time", None)),
        )

    @staticmethod
    def _on_job_error(event: Any) -> None:
        log.error(
            "orchestration.scheduler.job_error",
            job_id=getattr(event, "job_id", None),
            exception=str(getattr(event, "exception", None)),
        )

    def add_job(self, spec: JobSpec) -> None:
        scheduler = self._ensure()
        scheduler.add_job(
            spec.fn,
            trigger="cron",
            id=spec.name,
            name=spec.name,
            replace_existing=True,
            **spec.cron_kwargs,
        )
        self._registered[spec.name] = spec

    async def start(self) -> None:
        scheduler = self._ensure()
        loop = asyncio.get_running_loop()
        # APScheduler 3.x only adopts the running loop in ``start()`` when its
        # ``_eventloop`` is unset or closed; a stale-but-open loop pinned from an
        # earlier context would silently swallow every ``call_later`` wakeup.
        # Re-point it at the LIVE loop before starting so the wakeup chain is
        # delivered where it is actually processed.
        if getattr(scheduler, "_eventloop", None) is not loop:
            scheduler._eventloop = loop
        if not scheduler.running:
            scheduler.start()
        # WHY the watchdog: APScheduler 3.x drives itself off a SINGLE
        # self-rescheduling ``call_later`` wakeup — each wakeup runs
        # ``_process_jobs`` then arms the next timer. If any one link fails to
        # re-arm (observed in prod 2026-06-29: the chain fired ONCE then stalled
        # for ~33h with NO job-error/missed event, because the break is in the
        # timer plumbing, not a job), every future run vanishes silently and all
        # cron jobs freeze. Re-poke ``wakeup()`` from a task on the live loop so
        # ``_process_jobs`` runs (and re-arms the timer) every
        # ``_WAKEUP_WATCHDOG_SECONDS`` regardless of the internal timer's health.
        # Idempotent: ``_process_jobs`` only fires jobs whose ``next_run_time``
        # is due, so an extra poke never double-runs a job.
        if self._watchdog_task is None or self._watchdog_task.done():
            self._watchdog_task = loop.create_task(self._wakeup_watchdog())

    async def _wakeup_watchdog(self) -> None:
        """Periodically re-poke the scheduler so a dead internal wakeup-timer
        chain can never silently freeze every cron job (see :meth:`start`)."""
        while True:
            try:
                await asyncio.sleep(_WAKEUP_WATCHDOG_SECONDS)
            except asyncio.CancelledError:
                raise
            scheduler = self._scheduler
            if scheduler is None or not scheduler.running:
                return
            try:
                scheduler.wakeup()
            except Exception as exc:  # a watchdog hiccup must never kill the task
                log.warning(
                    "orchestration.scheduler.watchdog_wakeup_failed",
                    error=str(exc),
                )

    async def shutdown(self) -> None:
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            self._watchdog_task = None
        if self._scheduler is None or not self._scheduler.running:
            return
        # `wait=False` — return immediately; in-flight jobs continue to
        # completion. Process shutdown awaits the asyncio loop drain.
        self._scheduler.shutdown(wait=False)

    def list_jobs(self) -> list[JobSpec]:
        return list(self._registered.values())

    @property
    def is_running(self) -> bool:
        return self._scheduler is not None and self._scheduler.running


def build_apscheduler_adapter_from_env() -> APSchedulerAdapter:
    """Composition-root helper — builds an :class:`APSchedulerAdapter`."""
    from iguanatrader.config.secrets import SecretEnv

    secrets = SecretEnv()
    return APSchedulerAdapter(jobstore_url=f"sqlite:///{secrets.database_path}")


__all__ = ["APSchedulerAdapter", "build_apscheduler_adapter_from_env"]
