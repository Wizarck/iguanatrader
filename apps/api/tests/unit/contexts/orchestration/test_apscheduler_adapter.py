"""Unit tests for :class:`APSchedulerAdapter` (slice deployment-foundation §3.C).

The APScheduler SDK is mocked via injection — we pass a ``MagicMock``
``AsyncIOScheduler`` directly into the constructor and verify the
shim's wiring (``add_job`` args, ``start`` idempotency, ``shutdown``
no-op when not running).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from iguanatrader.contexts.orchestration.apscheduler_adapter import APSchedulerAdapter
from iguanatrader.contexts.orchestration.scheduler import JobSpec


async def _noop() -> None:
    return None


@pytest.fixture
def scheduler_mock() -> MagicMock:
    mock = MagicMock()
    mock.running = False
    mock.add_job = MagicMock()
    mock.start = MagicMock()
    mock.shutdown = MagicMock()
    return mock


def test_add_job_passes_cron_kwargs_to_scheduler(scheduler_mock: MagicMock) -> None:
    adapter = APSchedulerAdapter(jobstore_url="sqlite:///:memory:", scheduler=scheduler_mock)
    spec = JobSpec(
        name="premarket_research",
        fn=_noop,
        cron_kwargs={"hour": 8, "minute": 0, "day_of_week": "mon-fri"},
    )

    adapter.add_job(spec)

    scheduler_mock.add_job.assert_called_once()
    _, kwargs = scheduler_mock.add_job.call_args
    assert kwargs["id"] == "premarket_research"
    assert kwargs["trigger"] == "cron"
    assert kwargs["replace_existing"] is True
    assert kwargs["hour"] == 8
    assert kwargs["minute"] == 0
    assert kwargs["day_of_week"] == "mon-fri"


def test_list_jobs_returns_registered_specs(scheduler_mock: MagicMock) -> None:
    adapter = APSchedulerAdapter(jobstore_url="sqlite:///:memory:", scheduler=scheduler_mock)
    spec = JobSpec(name="weekly_review", fn=_noop, cron_kwargs={"day_of_week": "fri"})
    adapter.add_job(spec)

    assert adapter.list_jobs() == [spec]


@pytest.mark.asyncio
async def test_start_calls_scheduler_when_not_running(scheduler_mock: MagicMock) -> None:
    adapter = APSchedulerAdapter(jobstore_url="sqlite:///:memory:", scheduler=scheduler_mock)

    await adapter.start()

    scheduler_mock.start.assert_called_once()


@pytest.mark.asyncio
async def test_start_is_idempotent_when_already_running(
    scheduler_mock: MagicMock,
) -> None:
    scheduler_mock.running = True
    adapter = APSchedulerAdapter(jobstore_url="sqlite:///:memory:", scheduler=scheduler_mock)

    await adapter.start()

    scheduler_mock.start.assert_not_called()


@pytest.mark.asyncio
async def test_shutdown_calls_scheduler_when_running(scheduler_mock: MagicMock) -> None:
    scheduler_mock.running = True
    adapter = APSchedulerAdapter(jobstore_url="sqlite:///:memory:", scheduler=scheduler_mock)

    await adapter.shutdown()

    scheduler_mock.shutdown.assert_called_once_with(wait=False)


@pytest.mark.asyncio
async def test_shutdown_is_noop_when_scheduler_not_built() -> None:
    adapter = APSchedulerAdapter(jobstore_url="sqlite:///:memory:")

    await adapter.shutdown()  # no scheduler injected, no SDK lazy-import — should not raise.


def test_is_running_reflects_scheduler_state(scheduler_mock: MagicMock) -> None:
    adapter = APSchedulerAdapter(jobstore_url="sqlite:///:memory:", scheduler=scheduler_mock)
    assert adapter.is_running is False

    scheduler_mock.running = True
    assert adapter.is_running is True


@pytest.mark.asyncio
async def test_real_scheduler_starts_with_non_picklable_job() -> None:
    # Regression: production routines are bound methods / closures over
    # in-memory daemon services. A persistent (pickling) jobstore raised
    # "This Job cannot be serialized since the reference to its callable
    # could not be determined" at start(), crash-looping the full-mode
    # daemon. With MemoryJobStore the adapter must add such a callable and
    # start cleanly. Builds the REAL AsyncIOScheduler (no mock injected).
    pytest.importorskip("apscheduler.schedulers.asyncio")  # SDK absent in some local envs.
    calls: list[int] = []

    async def _tick() -> None:  # closure → not importable → not picklable
        calls.append(1)

    adapter = APSchedulerAdapter(jobstore_url="sqlite:///:memory:")
    adapter.add_job(JobSpec(name="premarket_research", fn=_tick, cron_kwargs={"hour": 8}))
    try:
        await adapter.start()  # must not raise on the non-picklable callable.
        assert adapter.is_running is True
    finally:
        await adapter.shutdown()
