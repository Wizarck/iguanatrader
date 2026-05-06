"""Unit tests for the in-memory scheduler (slice O2)."""

from __future__ import annotations

import pytest
from iguanatrader.contexts.orchestration.scheduler import InMemoryScheduler, JobSpec


@pytest.mark.asyncio
async def test_register_and_list_jobs() -> None:
    scheduler = InMemoryScheduler()

    async def noop() -> None:
        return None

    scheduler.add_job(JobSpec(name="premarket", fn=noop, cron_kwargs={"hour": 6}))
    scheduler.add_job(JobSpec(name="midday", fn=noop, cron_kwargs={"hour": 12}))
    jobs = scheduler.list_jobs()
    assert len(jobs) == 2
    assert {j.name for j in jobs} == {"premarket", "midday"}


@pytest.mark.asyncio
async def test_start_and_shutdown_idempotent() -> None:
    scheduler = InMemoryScheduler()
    assert scheduler.is_running is False
    await scheduler.start()
    assert scheduler.is_running is True
    await scheduler.shutdown()
    assert scheduler.is_running is False
    await scheduler.shutdown()  # idempotent
    assert scheduler.is_running is False


@pytest.mark.asyncio
async def test_register_overwrites_same_name() -> None:
    scheduler = InMemoryScheduler()

    async def fn1() -> None:
        return None

    async def fn2() -> None:
        return None

    scheduler.add_job(JobSpec(name="premarket", fn=fn1, cron_kwargs={"hour": 6}))
    scheduler.add_job(JobSpec(name="premarket", fn=fn2, cron_kwargs={"hour": 7}))
    jobs = scheduler.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].cron_kwargs == {"hour": 7}
