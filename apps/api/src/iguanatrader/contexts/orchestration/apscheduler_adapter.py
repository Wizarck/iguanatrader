# mypy: disable-error-code="no-any-unimported"
"""Production :class:`SchedulerProtocol` adapter wrapping APScheduler.

Resolves the deferred-install carry-forward from slice O2: the
:class:`InMemoryScheduler` fake stays for tests; production composition
root constructs this adapter and registers cron jobs via
:meth:`OrchestrationService.bootstrap_routines`.

Persistence: ``SQLAlchemyJobStore`` against the same SQLite the rest
of the API uses — jobs survive process restart so a missed daily
"premarket_research" run during a deploy is rescheduled correctly per
the APScheduler ``misfire_grace_time`` setting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from iguanatrader.contexts.orchestration.scheduler import JobSpec

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler


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
            from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
            from apscheduler.schedulers.asyncio import AsyncIOScheduler

            self._scheduler = AsyncIOScheduler(
                jobstores={"default": SQLAlchemyJobStore(url=self._jobstore_url)},
                timezone=self._timezone,
                job_defaults={"misfire_grace_time": _DEFAULT_MISFIRE_GRACE_SECONDS},
            )
        return self._scheduler

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
