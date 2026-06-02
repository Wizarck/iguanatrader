"""#2/#27/#29: bootstrap_routines runs each propose tick through the
``propose_unit_of_work`` wrapper (per-tick session + publish-after-commit).

Once the bus delivers per-event, a propose tick MUST commit its proposal row
before publishing ``ProposalCreated`` — otherwise the risk subscriber's fresh
session would not see it. This locks the wiring: the registered propose
JobSpec.fn invokes the supplied wrapper, and the no-wrapper path (older/test
setups) runs the tick directly.
"""

from __future__ import annotations

from typing import Any

import pytest
from iguanatrader.contexts.orchestration.service import OrchestrationService


class _FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[Any] = []

    def add_job(self, spec: Any) -> None:
        self.jobs.append(spec)


class _NoConfigsRepo:
    async def list_enabled_for_symbol(self, symbol: str) -> list[Any]:
        return []


class _UnusedMarketData:
    async def get_bars(self, **_: Any) -> Any:  # pragma: no cover - never reached
        raise AssertionError("get_bars must not be called when there are no configs")


_PROPOSE_ROUTINES = {"premarket", "midday", "postmarket", "weekly_review"}


async def _bootstrap(scheduler: _FakeScheduler, uow: Any) -> None:
    svc = OrchestrationService(repository=object())  # type: ignore[arg-type]  # repo unused
    await svc.bootstrap_routines(
        scheduler=scheduler,
        trading_service=object(),
        watchlist_symbols=["AAPL"],
        market_data_port=_UnusedMarketData(),
        strategy_config_repo=_NoConfigsRepo(),
        propose_unit_of_work=uow,
    )


@pytest.mark.asyncio
async def test_propose_tick_runs_through_unit_of_work() -> None:
    scheduler = _FakeScheduler()
    calls: list[str] = []

    async def uow(inner: Any) -> None:
        calls.append("uow")
        await inner()

    await _bootstrap(scheduler, uow)

    propose_jobs = [j for j in scheduler.jobs if j.name in _PROPOSE_ROUTINES]
    assert len(propose_jobs) == 4
    # Triggering a registered propose tick goes through the wrapper.
    await propose_jobs[0].fn()
    assert calls == ["uow"]


@pytest.mark.asyncio
async def test_propose_tick_runs_directly_without_wrapper() -> None:
    scheduler = _FakeScheduler()
    await _bootstrap(scheduler, None)

    propose_jobs = [j for j in scheduler.jobs if j.name in _PROPOSE_ROUTINES]
    assert len(propose_jobs) == 4
    # No wrapper: the tick runs directly (no error; no configs → no-op).
    await propose_jobs[0].fn()
