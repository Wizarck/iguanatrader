"""Scheduler Protocol + in-memory fake (slice O2).

Production wiring uses ``APScheduler.AsyncIOScheduler`` with a
``SQLAlchemyJobStore`` — that lands in the deployment-foundation slice
along with the dep + secret-handling. R2 ships the Protocol + an
in-memory fake (:class:`InMemoryScheduler`) so the orchestration
service is fully testable without the real scheduler dep.

The Protocol surface mirrors the canonical APScheduler API the service
consumes: ``add_job(func, trigger="cron", **cron_kwargs)`` + ``start()``
+ ``shutdown()``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

JobFn = Callable[[], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class JobSpec:
    """Cron-style job specification — what the service registers per routine."""

    name: str
    fn: JobFn
    cron_kwargs: dict[str, Any] = field(default_factory=dict)


class SchedulerProtocol(Protocol):
    """Minimal scheduler surface :class:`OrchestrationService` consumes."""

    def add_job(self, spec: JobSpec) -> None:
        """Register a cron-fired job."""
        ...

    async def start(self) -> None:
        """Start the scheduler (blocking until ``shutdown`` is called)."""
        ...

    async def shutdown(self) -> None:
        """Stop the scheduler. Idempotent."""
        ...

    def list_jobs(self) -> list[JobSpec]:
        """Return registered jobs."""
        ...


class InMemoryScheduler:
    """Minimal in-memory :class:`SchedulerProtocol` implementation.

    Used by tests + the slice O2 default service wiring (until
    APScheduler lands). Tests drive the service via
    :meth:`OrchestrationService.run_routine` directly; this scheduler
    is registered + introspected but never actually fires cron triggers
    in CI.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, JobSpec] = {}
        self._running: bool = False

    def add_job(self, spec: JobSpec) -> None:
        self._jobs[spec.name] = spec

    async def start(self) -> None:
        self._running = True

    async def shutdown(self) -> None:
        self._running = False

    def list_jobs(self) -> list[JobSpec]:
        return list(self._jobs.values())

    @property
    def is_running(self) -> bool:
        return self._running


__all__ = ["InMemoryScheduler", "JobFn", "JobSpec", "SchedulerProtocol"]
