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

Hang containment (2026-06-29 incident — every cron silently froze for
~33h): APScheduler runs each due job as an asyncio Task and tracks a
per-job running-instance counter, decremented only when the Task's
done-callback fires. With ``max_instances=1`` a single tick that hangs
on an UNCAPPED ``await`` (a wedged IBKR socket or a stalled DB
statement) never completes, so the slot stays pinned and EVERY later
tick is refused with ``EVENT_JOB_MAX_INSTANCES`` — a signal the adapter
did not listen for, so all future runs of that job vanished with no
error, no missed event. Fix: :func:`_with_timeout` bounds every job
body so a hang becomes a ``TimeoutError`` (→ ``EVENT_JOB_ERROR``, slot
released, next tick runs), and we now surface ``MAX_INSTANCES`` +
``EXECUTED`` so the chain can never stall unobserved again. The real
triggers are capped at source too (asyncpg ``command_timeout`` +
``pool_pre_ping`` in ``persistence.session``; ``asyncio.timeout`` on the
IBKR reads in ``ib_async_client``).
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import structlog

from iguanatrader.contexts.orchestration.scheduler import JobSpec

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler


log = structlog.get_logger("iguanatrader.contexts.orchestration.apscheduler_adapter")

_DEFAULT_TIMEZONE = ZoneInfo("America/New_York")
_DEFAULT_MISFIRE_GRACE_SECONDS = 300
#: Hard ceiling on any single cron-job body. A tick exceeding this is treated as
#: hung: it raises ``TimeoutError`` so the executor's done-callback fires, the
#: ``max_instances`` slot is released, and the next tick can run — instead of one
#: hang silently freezing the job forever. Must exceed the slowest legitimate job
#: (``market_data_sync`` ingests ~44 symbols, ~50s) yet stay under
#: ``misfire_grace_time`` (300s).
_DEFAULT_JOB_TIMEOUT_SECONDS = 180
#: Belt-and-suspenders heartbeat: re-poke the scheduler every N seconds so even a
#: pathological internal-timer stall can't keep due jobs from being processed.
_WAKEUP_WATCHDOG_SECONDS = 20


def _with_timeout(
    fn: Callable[..., Awaitable[Any]],
    *,
    timeout: float,
    job_id: str,
) -> Callable[..., Awaitable[Any]]:
    """Wrap a coroutine cron body with a hard timeout.

    A hang becomes a ``TimeoutError`` — re-raised so APScheduler's executor
    done-callback fires, the ``max_instances`` slot is released, and a
    ``EVENT_JOB_ERROR`` is emitted. Without this, one uncapped ``await`` freezes
    the job permanently and silently (see module docstring).
    """

    @functools.wraps(fn)
    async def _runner(*args: Any, **kwargs: Any) -> Any:
        try:
            async with asyncio.timeout(timeout):
                return await fn(*args, **kwargs)
        except TimeoutError:
            log.error(
                "orchestration.scheduler.job_timeout",
                job_id=job_id,
                timeout_s=timeout,
            )
            raise

    return _runner


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
            from apscheduler.events import (
                EVENT_JOB_ERROR,
                EVENT_JOB_EXECUTED,
                EVENT_JOB_MAX_INSTANCES,
                EVENT_JOB_MISSED,
            )
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
                    # #21: keep ``max_instances=1`` — overlapping runs of the
                    # same sweep would race. Safe now that ``_with_timeout``
                    # guarantees a tick can never hold the slot beyond the
                    # timeout (the 2026-06-29 silent-freeze fix).
                    "max_instances": 1,
                    "coalesce": True,
                },
            )
            # Surface EVERY terminal signal. ``MAX_INSTANCES`` was the silent one
            # in the 2026-06-29 incident (a hung tick pinned the slot, refusing
            # all later ticks with no error/missed). ``EXECUTED`` gives positive
            # confirmation each sweep actually completed.
            self._scheduler.add_listener(self._on_job_missed, EVENT_JOB_MISSED)
            self._scheduler.add_listener(self._on_job_error, EVENT_JOB_ERROR)
            self._scheduler.add_listener(self._on_job_max_instances, EVENT_JOB_MAX_INSTANCES)
            self._scheduler.add_listener(self._on_job_executed, EVENT_JOB_EXECUTED)
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

    @staticmethod
    def _on_job_max_instances(event: Any) -> None:
        # The signal that was silent in the freeze: a prior tick is still
        # running, so this one was refused. With ``_with_timeout`` this is now
        # self-healing, but surface it so a chronically-overrunning sweep shows.
        log.error(
            "orchestration.scheduler.job_max_instances",
            job_id=getattr(event, "job_id", None),
            scheduled_run_time=str(getattr(event, "scheduled_run_time", None)),
        )

    @staticmethod
    def _on_job_executed(event: Any) -> None:
        log.info(
            "orchestration.scheduler.job_executed",
            job_id=getattr(event, "job_id", None),
        )

    def add_job(self, spec: JobSpec) -> None:
        scheduler = self._ensure()
        # Bound every job body with a hard timeout so a hung tick can never
        # silently freeze the job (the 2026-06-29 incident root cause).
        fn = _with_timeout(spec.fn, timeout=_DEFAULT_JOB_TIMEOUT_SECONDS, job_id=spec.name)
        scheduler.add_job(
            fn,
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
        # AsyncIOScheduler submits each job via ``_eventloop.create_task`` against
        # the loop captured at start(); if that ever differed from the running
        # loop, every job would strand on a dormant loop with no error. Pin it to
        # the live loop so that failure mode is structurally impossible.
        if getattr(scheduler, "_eventloop", None) is not loop:
            scheduler._eventloop = loop
        if not scheduler.running:
            scheduler.start()
        # Belt-and-suspenders heartbeat: APScheduler 3.x self-reschedules a single
        # ``call_later`` wakeup; re-poking ``wakeup()`` from the live loop ensures
        # due jobs are always processed even if that internal timer ever stalls.
        # (The real freeze cause was hung job bodies, not this timer — see module
        # docstring — but the poke is cheap and idempotent: ``_process_jobs`` only
        # fires DUE jobs.)
        if self._watchdog_task is None or self._watchdog_task.done():
            self._watchdog_task = loop.create_task(self._wakeup_watchdog())
        log.info(
            "orchestration.scheduler.started",
            jobs=len(scheduler.get_jobs()),
            eventloop_is_running_loop=getattr(scheduler, "_eventloop", None) is loop,
        )

    async def _wakeup_watchdog(self) -> None:
        """Periodically re-poke the scheduler's wakeup as a liveness backstop."""
        while True:
            try:
                await asyncio.sleep(_WAKEUP_WATCHDOG_SECONDS)
            except asyncio.CancelledError:
                raise
            scheduler = self._scheduler
            if scheduler is None or not scheduler.running:
                return
            try:
                # ``wakeup()`` marshals onto the scheduler's own loop via
                # ``call_soon_threadsafe`` (the maintainer-intended path), so the
                # executor submits jobs onto the loop that is actually running.
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
