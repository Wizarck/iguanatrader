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

from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import structlog

from iguanatrader.contexts.orchestration.scheduler import JobSpec

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler


log = structlog.get_logger("iguanatrader.contexts.orchestration.apscheduler_adapter")

_DEFAULT_TIMEZONE = ZoneInfo("America/New_York")
_DEFAULT_MISFIRE_GRACE_SECONDS = 300


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
        if not scheduler.running:
            scheduler.start()

    async def shutdown(self) -> None:
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
