"""#29 (cron side): ``bootstrap_routines`` runs each session-only cron sweep
tick through the ``sweep_unit_of_work`` wrapper (fresh per-tick session +
commit + publish-after-commit), instead of sharing the long-lived ambient
daemon session.

Locks the wiring for all four session-only sweeps — trailing-stop, stop-hit,
equity-snapshot, daemon-heartbeat — so that two sweeps firing close together
(the 10s heartbeat overlapping the 1-min stop-hit sweep) no longer touch one
``AsyncSession`` concurrently. The no-wrapper path (older / test setups) runs
each tick directly on the ambient session.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from iguanatrader.contexts.orchestration.service import OrchestrationService

_SWEEP_NAMES = {
    "trailing_stops_sweep",
    "stop_hit_sweep",
    "equity_snapshot_sweep",
    "approval_timeout_sweep",
    "daemon_heartbeat",
}


class _FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[Any] = []

    def add_job(self, spec: Any) -> None:
        self.jobs.append(spec)


class _RecordingSweep:
    """Fake sweep service whose ``sweep()`` records the call + returns a
    zero-valued result namespace carrying every attribute the bootstrap
    logging reads (so no error path is taken)."""

    def __init__(self, **result_fields: int) -> None:
        self.swept = 0
        self._result_fields = result_fields

    async def sweep(self) -> SimpleNamespace:
        self.swept += 1
        return SimpleNamespace(**self._result_fields)


class _RecordingModeRepo:
    def __init__(self) -> None:
        self.heartbeats = 0

    async def write_heartbeat(self, *, tenant_id: Any, mode: str, ib_connected: bool) -> None:
        self.heartbeats += 1


class _RecordingApproval:
    """Fake approval service: records ``sweep_expired_requests`` + returns []."""

    def __init__(self) -> None:
        self.swept = 0

    async def sweep_expired_requests(self) -> list[Any]:
        self.swept += 1
        return []


class _RecordingBrief:
    """Fake brief-refresh service: records each ``refresh(symbol=, methodology=)``
    call so the test can assert the cron iterates the full watchlist with the
    house methodology. ``raise_for`` lets a test prove per-symbol fail-soft (one
    bad symbol never aborts the batch)."""

    def __init__(self, raise_for: set[str] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._raise_for = raise_for or set()

    async def refresh(self, *, symbol: str, methodology: str) -> None:
        self.calls.append((symbol, methodology))
        if symbol in self._raise_for:
            raise RuntimeError(f"boom:{symbol}")


def _make_sweeps() -> (
    tuple[_RecordingSweep, _RecordingSweep, _RecordingSweep, _RecordingModeRepo, _RecordingApproval]
):
    trailing = _RecordingSweep(
        trades_evaluated=0,
        trades_trailed=0,
        trades_no_update=0,
        trades_trigger_not_reached=0,
        trades_skipped_no_bars=0,
        duration_ms=0,
    )
    stop_hit = _RecordingSweep(
        trades_evaluated=0,
        stop_hits_emitted=0,
        target_hits_emitted=0,
        trades_skipped_no_bars=0,
        duration_ms=0,
    )
    equity = _RecordingSweep(
        tenants_evaluated=0,
        snapshots_persisted=0,
        broker_errors=0,
        duration_ms=0,
    )
    mode_repo = _RecordingModeRepo()
    approval = _RecordingApproval()
    return trailing, stop_hit, equity, mode_repo, approval


async def _bootstrap(
    scheduler: _FakeScheduler,
    *,
    trailing: Any,
    stop_hit: Any,
    equity: Any,
    mode_repo: Any,
    approval: Any,
    sweep_uow: Any,
    brief: Any = None,
    watchlist: list[str] | None = None,
) -> None:
    svc = OrchestrationService(repository=object())  # type: ignore[arg-type]
    await svc.bootstrap_routines(
        scheduler=scheduler,
        trading_service=object(),
        watchlist_symbols=watchlist if watchlist is not None else ["AAPL"],
        trailing_stop_sweep_service=trailing,
        stop_hit_sweep_service=stop_hit,
        equity_snapshot_sweep_service=equity,
        approval_service=approval,
        brief_refresh_service=brief,
        # daemon_* params: required to wire the heartbeat job. No lifecycle
        # service → the poll branch is skipped.
        daemon_mode="paper",
        daemon_tenant_id=uuid4(),
        trading_mode_repo=mode_repo,
        broker=SimpleNamespace(state=SimpleNamespace(value="connected")),
        sweep_unit_of_work=sweep_uow,
    )


@pytest.mark.asyncio
async def test_each_sweep_tick_runs_through_unit_of_work() -> None:
    scheduler = _FakeScheduler()
    trailing, stop_hit, equity, mode_repo, approval = _make_sweeps()
    calls: list[str] = []

    async def uow(inner: Any) -> None:
        calls.append("uow")
        await inner()

    await _bootstrap(
        scheduler,
        trailing=trailing,
        stop_hit=stop_hit,
        equity=equity,
        mode_repo=mode_repo,
        approval=approval,
        sweep_uow=uow,
    )

    sweep_jobs = {j.name: j for j in scheduler.jobs if j.name in _SWEEP_NAMES}
    assert set(sweep_jobs) == _SWEEP_NAMES

    # Triggering each registered sweep goes through the wrapper exactly once.
    for name in _SWEEP_NAMES:
        await sweep_jobs[name].fn()

    assert calls == ["uow"] * len(_SWEEP_NAMES)
    assert trailing.swept == 1
    assert stop_hit.swept == 1
    assert equity.swept == 1
    assert approval.swept == 1
    assert mode_repo.heartbeats == 1


@pytest.mark.asyncio
async def test_brief_refresh_cron_registered_and_iterates_watchlist() -> None:
    """``brief-refresh-daemon-cron``: when a ``brief_refresh_service`` is wired,
    bootstrap registers a ``research_briefs_refresh`` job whose tick runs through
    the per-tick ``sweep_unit_of_work`` and refreshes EVERY watchlist symbol with
    the house methodology — one bad symbol never aborts the batch (fail-soft)."""
    scheduler = _FakeScheduler()
    trailing, stop_hit, equity, mode_repo, approval = _make_sweeps()
    brief = _RecordingBrief(raise_for={"MSFT"})
    calls: list[str] = []

    async def uow(inner: Any) -> None:
        calls.append("uow")
        await inner()

    await _bootstrap(
        scheduler,
        trailing=trailing,
        stop_hit=stop_hit,
        equity=equity,
        mode_repo=mode_repo,
        approval=approval,
        sweep_uow=uow,
        brief=brief,
        watchlist=["AAPL", "MSFT", "GOOGL"],
    )

    brief_jobs = [j for j in scheduler.jobs if j.name == "research_briefs_refresh"]
    assert len(brief_jobs) == 1
    job = brief_jobs[0]
    # Daily pre-market (07:00 UTC), weekdays only — before the 08:00 propose tick.
    assert job.cron_kwargs == {"hour": "7", "minute": "0", "day_of_week": "mon-fri"}

    await job.fn()

    # Ran through the per-tick unit-of-work wrapper exactly once.
    assert calls == ["uow"]
    # Every symbol attempted with the house methodology, even past the raiser.
    assert brief.calls == [
        ("AAPL", "three_pillar"),
        ("MSFT", "three_pillar"),
        ("GOOGL", "three_pillar"),
    ]


@pytest.mark.asyncio
async def test_brief_refresh_cron_absent_when_service_not_wired() -> None:
    """No ``brief_refresh_service`` → no ``research_briefs_refresh`` job (the cron
    is opt-in via ``IGUANATRADER_BRIEF_REFRESH_ENABLED`` at the CLI boundary)."""
    scheduler = _FakeScheduler()
    trailing, stop_hit, equity, mode_repo, approval = _make_sweeps()

    await _bootstrap(
        scheduler,
        trailing=trailing,
        stop_hit=stop_hit,
        equity=equity,
        mode_repo=mode_repo,
        approval=approval,
        sweep_uow=None,
        brief=None,
    )

    assert not [j for j in scheduler.jobs if j.name == "research_briefs_refresh"]


@pytest.mark.asyncio
async def test_sweeps_run_directly_without_wrapper() -> None:
    scheduler = _FakeScheduler()
    trailing, stop_hit, equity, mode_repo, approval = _make_sweeps()

    await _bootstrap(
        scheduler,
        trailing=trailing,
        stop_hit=stop_hit,
        equity=equity,
        mode_repo=mode_repo,
        approval=approval,
        sweep_uow=None,
    )

    sweep_jobs = {j.name: j for j in scheduler.jobs if j.name in _SWEEP_NAMES}
    assert set(sweep_jobs) == _SWEEP_NAMES

    # No wrapper: each tick runs directly (no error; underlying sweep invoked).
    for name in _SWEEP_NAMES:
        await sweep_jobs[name].fn()

    assert trailing.swept == 1
    assert stop_hit.swept == 1
    assert equity.swept == 1
    assert approval.swept == 1
    assert mode_repo.heartbeats == 1
