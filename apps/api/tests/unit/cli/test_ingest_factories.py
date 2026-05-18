"""Unit tests for the I7 source-factory map + persist closure.

Pure-unit: no real adapters constructed (env-driven secrets would
raise :class:`ConfigError` in CI). The map test verifies coverage
(13 source ids matching the production research_sources rows from
migrations 0010 + 0019) and the persist-closure test exercises the
draft-stamping logic with a fake session/repository.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from iguanatrader.cli._ingest_factories import (
    build_persist_drafts_closure,
    build_source_factories,
)
from iguanatrader.contexts.research.ports import ResearchFactDraft

# ---------------------------------------------------------------------------
# Factory map coverage
# ---------------------------------------------------------------------------


_EXPECTED_SOURCE_IDS = frozenset(
    {
        # Tier-A — migration 0019
        "sec_edgar",
        "fred",
        "bea",
        "bls",
        # Tier-B/C — migration 0010
        "finnhub",
        "gdelt",
        "openfda",
        "vdem",
        "wgi_world_bank",
        # Internal sources without their own seed row but registered in
        # the codebase + wired by the manual CLI / scheduler.
        "openbb-sidecar",
        "ibkr",
        "motley-fool",
        "edgartools",
    }
)


def test_factory_map_covers_all_research_sources() -> None:
    """Every adapter present in the repo is exposed by the factory map.

    Regression-guard against the "registered in DB migration but no
    code-side wiring" orphan pattern we fixed in this slice.
    """
    factories = build_source_factories()
    assert set(factories.keys()) == _EXPECTED_SOURCE_IDS


def test_factory_entries_are_callable() -> None:
    """Each entry must be a zero-arg callable; the scheduler invokes
    ``factory()`` at job-tick time."""
    factories = build_source_factories()
    for source_id, fn in factories.items():
        assert callable(fn), f"factory for {source_id!r} is not callable"


# ---------------------------------------------------------------------------
# persist_drafts closure
# ---------------------------------------------------------------------------


@dataclass
class _CapturedDraft:
    source_id: str
    symbol_universe_id: UUID | None
    fact_kind: str


class _FakeRepo:
    """Records every insert_fact call for assertions."""

    def __init__(self) -> None:
        self.inserted: list[_CapturedDraft] = []

    async def insert_fact(self, draft: ResearchFactDraft) -> None:
        self.inserted.append(
            _CapturedDraft(
                source_id=draft.source_id,
                symbol_universe_id=draft.symbol_universe_id,
                fact_kind=draft.fact_kind,
            )
        )


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


def _make_draft(source_id: str = "sec_edgar") -> ResearchFactDraft:
    return ResearchFactDraft(
        source_id=source_id,
        fact_kind="sec_xbrl.us-gaap.EarningsPerShareDiluted",
        effective_from=datetime(2026, 5, 1, tzinfo=UTC),
        recorded_from=datetime(2026, 5, 1, tzinfo=UTC),
        source_url="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany",
        retrieval_method="api",
        retrieved_at=datetime(2026, 5, 1, tzinfo=UTC),
        value_numeric=None,
        value_text="3.50",
        value_jsonb=None,
        dedupe_key=f"sec_edgar:test:{uuid4()}",
    )


def test_persist_closure_stamps_symbol_universe_id_and_counts(monkeypatch: Any) -> None:
    """The closure rewrites each draft's symbol_universe_id before
    insert, returns the count of successfully inserted rows, and
    commits once at the end."""
    fake_repo = _FakeRepo()
    fake_session = _FakeSession()

    monkeypatch.setattr(
        "iguanatrader.cli._ingest_factories.ResearchRepository",
        lambda: fake_repo,
    )

    def _sessionmaker() -> _FakeSession:
        return fake_session

    persist = build_persist_drafts_closure(sessionmaker=_sessionmaker)

    su_id = uuid4()
    drafts = [_make_draft(), _make_draft(), _make_draft()]
    count: int = asyncio.run(persist(drafts, su_id))  # type: ignore[arg-type]

    assert count == 3
    assert fake_session.committed is True
    assert [d.symbol_universe_id for d in fake_repo.inserted] == [su_id, su_id, su_id]


def test_persist_closure_swallows_per_draft_errors(monkeypatch: Any) -> None:
    """A single insert failure must not abort the rest of the batch —
    the scheduler relies on this for failure-isolation across drafts
    in the same job tick."""

    class _FailingRepo:
        def __init__(self) -> None:
            self.calls = 0

        async def insert_fact(self, draft: ResearchFactDraft) -> None:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("boom")

    failing = _FailingRepo()
    monkeypatch.setattr(
        "iguanatrader.cli._ingest_factories.ResearchRepository",
        lambda: failing,
    )

    def _sessionmaker() -> _FakeSession:
        return _FakeSession()

    persist = build_persist_drafts_closure(sessionmaker=_sessionmaker)
    count_failed: int = asyncio.run(persist([_make_draft(), _make_draft(), _make_draft()], uuid4()))  # type: ignore[arg-type]
    assert count_failed == 2
    assert failing.calls == 3
