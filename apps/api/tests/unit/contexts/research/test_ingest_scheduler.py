# ruff: noqa: RUF003
"""Unit tests for the I7 ingest scheduler service.

Pure-unit — no APScheduler, no DB, no live adapters. A fake scheduler
buffers JobSpecs; a fake recorder buffers start/finish calls; a fake
source returns canned drafts. Verifies:

* schedule → cron kwargs mapping (daily / weekly / manual)
* ``brief_refresh_cron`` overrides the canonical mapping
* disabled watchlist rows are skipped
* job function records start → invokes adapter → persists → records finish
* adapter failure persists an `error` row but does not crash the scheduler
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from iguanatrader.contexts.research.ingest_scheduler import (
    IngestRunRecorder,
    IngestSchedulerService,
    WatchlistRow,
)
from iguanatrader.contexts.research.ports import ResearchFactDraft


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _row(
    *,
    schedule: str = "daily",
    cron: str | None = None,
    enabled: bool = True,
    symbol: str = "NVDA",
) -> WatchlistRow:
    return WatchlistRow(
        tenant_id=uuid4(),
        symbol_universe_id=uuid4(),
        symbol=symbol,
        brief_refresh_schedule=schedule,
        brief_refresh_cron=cron,
        enabled=enabled,
    )


def _draft(symbol: str = "NVDA") -> ResearchFactDraft:
    now = datetime(2026, 5, 15, tzinfo=UTC)
    return ResearchFactDraft(
        source_id="test",
        fact_kind="test_fact",
        effective_from=now,
        recorded_from=now,
        source_url="test://x",
        retrieval_method="api",
        retrieved_at=now,
        fact_metadata={"symbol": symbol},
    )


class _FakeRecorder(IngestRunRecorder):
    """Bypass the session-provider plumbing — store rows in memory."""

    def __init__(self) -> None:
        # Skip super().__init__ — no session provider needed.
        self.starts: list[dict[str, Any]] = []
        self.finishes: list[dict[str, Any]] = []
        self._next_id = uuid4

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
        self.starts.append(
            {
                "run_id": run_id,
                "tenant_id": tenant_id,
                "source_id": source_id,
                "symbol": symbol,
                "symbol_universe_id": symbol_universe_id,
                "invoked_by": invoked_by,
            }
        )
        return run_id

    async def record_finish(
        self,
        *,
        run_id: UUID,
        facts_inserted: int,
        error_detail: str | None = None,
    ) -> None:
        self.finishes.append(
            {
                "run_id": run_id,
                "facts_inserted": facts_inserted,
                "error_detail": error_detail,
            }
        )


class _FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[Any] = []

    def add_job(self, spec: Any) -> None:
        self.jobs.append(spec)


class _FakeSource:
    def __init__(self, *, drafts: list[ResearchFactDraft] | Exception) -> None:
        self._drafts = drafts

    async def fetch_async(self, symbol: str) -> list[ResearchFactDraft]:
        if isinstance(self._drafts, Exception):
            raise self._drafts
        return list(self._drafts)


# ---------------------------------------------------------------------------
# Spec construction
# ---------------------------------------------------------------------------


def test_daily_schedule_maps_to_06_00_utc_cron() -> None:
    svc = IngestSchedulerService(recorder=_FakeRecorder())
    specs = svc.build_specs(
        watchlist=[_row(schedule="daily")],
        sources={"ibkr": lambda: _FakeSource(drafts=[])},
        persist_drafts=lambda drafts, suid: _async_int(0),
    )
    assert len(specs) == 1
    assert specs[0].cron_kwargs == {"hour": 6, "minute": 0}


def test_weekly_schedule_maps_to_monday_06_00() -> None:
    svc = IngestSchedulerService(recorder=_FakeRecorder())
    specs = svc.build_specs(
        watchlist=[_row(schedule="weekly")],
        sources={"ibkr": lambda: _FakeSource(drafts=[])},
        persist_drafts=lambda drafts, suid: _async_int(0),
    )
    assert specs[0].cron_kwargs == {"day_of_week": "mon", "hour": 6, "minute": 0}


def test_manual_schedule_is_skipped() -> None:
    svc = IngestSchedulerService(recorder=_FakeRecorder())
    specs = svc.build_specs(
        watchlist=[_row(schedule="manual")],
        sources={"ibkr": lambda: _FakeSource(drafts=[])},
        persist_drafts=lambda drafts, suid: _async_int(0),
    )
    assert specs == []


def test_custom_cron_overrides_canonical_mapping() -> None:
    svc = IngestSchedulerService(recorder=_FakeRecorder())
    specs = svc.build_specs(
        watchlist=[_row(schedule="daily", cron="*/30 * * * *")],
        sources={"ibkr": lambda: _FakeSource(drafts=[])},
        persist_drafts=lambda drafts, suid: _async_int(0),
    )
    assert specs[0].cron_kwargs == {"crontab": "*/30 * * * *"}


def test_disabled_row_is_skipped() -> None:
    svc = IngestSchedulerService(recorder=_FakeRecorder())
    specs = svc.build_specs(
        watchlist=[_row(enabled=False)],
        sources={"ibkr": lambda: _FakeSource(drafts=[])},
        persist_drafts=lambda drafts, suid: _async_int(0),
    )
    assert specs == []


def test_one_spec_per_source_per_row() -> None:
    svc = IngestSchedulerService(recorder=_FakeRecorder())
    specs = svc.build_specs(
        watchlist=[_row(symbol="NVDA"), _row(symbol="AMD")],
        sources={
            "ibkr": lambda: _FakeSource(drafts=[]),
            "openbb-sidecar": lambda: _FakeSource(drafts=[]),
        },
        persist_drafts=lambda drafts, suid: _async_int(0),
    )
    # 2 symbols × 2 sources → 4 specs.
    assert len(specs) == 4
    symbols = sorted({s.symbol for s in specs if s.symbol is not None})
    assert symbols == ["AMD", "NVDA"]


# ---------------------------------------------------------------------------
# Bootstrap into scheduler
# ---------------------------------------------------------------------------


def test_bootstrap_registers_jobs_with_scheduler() -> None:
    scheduler = _FakeScheduler()
    svc = IngestSchedulerService(recorder=_FakeRecorder())
    svc.bootstrap_ingest_routines(
        scheduler=scheduler,
        watchlist=[_row()],
        sources={"ibkr": lambda: _FakeSource(drafts=[])},
        persist_drafts=lambda drafts, suid: _async_int(0),
    )
    assert len(scheduler.jobs) == 1
    job = scheduler.jobs[0]
    assert job.name.startswith("research_ingest::ibkr::NVDA::")


# ---------------------------------------------------------------------------
# Job function happy path
# ---------------------------------------------------------------------------


def test_job_fn_records_start_invokes_adapter_records_finish() -> None:
    recorder = _FakeRecorder()
    svc = IngestSchedulerService(recorder=recorder)

    drafts = [_draft("NVDA"), _draft("NVDA")]
    persisted: list[int] = []

    async def _persist(drafts_iter: Iterable[ResearchFactDraft], suid: UUID) -> int:
        n = sum(1 for _ in drafts_iter)
        persisted.append(n)
        return n

    specs = svc.build_specs(
        watchlist=[_row()],
        sources={"ibkr": lambda: _FakeSource(drafts=drafts)},
        persist_drafts=_persist,
    )
    _run(specs[0].fn())

    assert len(recorder.starts) == 1
    assert recorder.starts[0]["source_id"] == "ibkr"
    assert len(recorder.finishes) == 1
    finish = recorder.finishes[0]
    assert finish["facts_inserted"] == 2
    assert finish["error_detail"] is None
    assert persisted == [2]


def test_job_fn_records_error_when_adapter_raises() -> None:
    recorder = _FakeRecorder()
    svc = IngestSchedulerService(recorder=recorder)

    async def _persist(drafts: Iterable[ResearchFactDraft], suid: UUID) -> int:
        return 0

    specs = svc.build_specs(
        watchlist=[_row()],
        sources={"ibkr": lambda: _FakeSource(drafts=RuntimeError("TWS down"))},
        persist_drafts=_persist,
    )
    # Failure path must NOT raise — scheduler ticks should never crash
    # because one source went down.
    _run(specs[0].fn())

    assert len(recorder.finishes) == 1
    finish = recorder.finishes[0]
    assert finish["facts_inserted"] == 0
    assert finish["error_detail"] is not None
    assert "TWS down" in finish["error_detail"]


def test_job_fn_records_error_when_persist_raises() -> None:
    recorder = _FakeRecorder()
    svc = IngestSchedulerService(recorder=recorder)

    async def _persist(drafts: Iterable[ResearchFactDraft], suid: UUID) -> int:
        raise RuntimeError("DB constraint violation")

    specs = svc.build_specs(
        watchlist=[_row()],
        sources={"ibkr": lambda: _FakeSource(drafts=[_draft()])},
        persist_drafts=_persist,
    )
    _run(specs[0].fn())

    assert recorder.finishes[0]["error_detail"] is not None
    assert "DB constraint" in recorder.finishes[0]["error_detail"]


def test_job_fn_falls_back_to_sync_fetch_when_no_fetch_async() -> None:
    """An older adapter exposing only the sync ``fetch(symbol, since)``
    SourcePort method must still be schedulable."""

    class _SyncOnlySource:
        def fetch(self, symbol: str, since: Any) -> list[ResearchFactDraft]:
            return [_draft(symbol)]

    recorder = _FakeRecorder()
    svc = IngestSchedulerService(recorder=recorder)

    async def _persist(drafts: Iterable[ResearchFactDraft], suid: UUID) -> int:
        return sum(1 for _ in drafts)

    specs = svc.build_specs(
        watchlist=[_row()],
        sources={"legacy": lambda: _SyncOnlySource()},
        persist_drafts=_persist,
    )
    _run(specs[0].fn())

    assert recorder.finishes[0]["facts_inserted"] == 1
    assert recorder.finishes[0]["error_detail"] is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _async_int(n: int) -> int:
    return n
