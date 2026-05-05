"""Provenance + hybrid-payload + append-only enforcement.

Covers spec scenarios under:

* "research_facts rejects inserts missing provenance metadata".
* "research_facts payload storage uses hybrid 16KB threshold with sha256
  integrity".
* "research_facts, research_briefs, corporate_events, analyst_ratings are
  append-only at L1 + L2".

Bug-for-bug compatibility note: the SQLAlchemy ORM constructs an
:class:`IntegrityError` even for our `MissingProvenanceError`-lift path —
we assert the lifted class, not the underlying driver class.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.research.errors import MissingProvenanceError
from iguanatrader.contexts.research.models import ResearchFact
from iguanatrader.contexts.research.ports import (
    PAYLOAD_INLINE_THRESHOLD,
    ResearchFactDraft,
)
from iguanatrader.contexts.research.repository import ResearchRepository
from iguanatrader.persistence.errors import AppendOnlyViolationError
from iguanatrader.shared.contextvars import with_tenant_context
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

T1 = datetime(2024, 4, 25, 10, 0, 0, tzinfo=UTC)


def _valid_draft(*, source_id: str, universe_id: UUID) -> ResearchFactDraft:
    return ResearchFactDraft(
        source_id=source_id,
        symbol_universe_id=universe_id,
        fact_kind="fundamental.eps",
        effective_from=T1,
        recorded_from=T1,
        source_url="https://example.test/edgar/AAPL.json",
        retrieval_method="api",
        retrieved_at=T1,
        value_numeric=Decimal("1.0"),
    ).with_payload(b'{"raw": "ok"}')


# ---------------------------------------------------------------------------
# Provenance NOT NULL + CHECK enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_insert_with_null_source_id_raises_missing_provenance(
    seeded_world: dict[str, Any],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]

    async with with_tenant_context(tenant_id):
        bad = ResearchFactDraft(
            source_id=None,  # type: ignore[arg-type]
            symbol_universe_id=universe_id,
            fact_kind="fundamental.eps",
            effective_from=T1,
            recorded_from=T1,
            source_url="https://example.test/x.json",
            retrieval_method="api",
            retrieved_at=T1,
            value_numeric=Decimal("1.0"),
        ).with_payload(b'{"raw": "ok"}')
        with pytest.raises(MissingProvenanceError):
            await repository.insert_fact(bad)


@pytest.mark.asyncio
async def test_insert_with_empty_source_url_raises(
    seeded_world: dict[str, Any],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]

    async with with_tenant_context(tenant_id):
        bad = ResearchFactDraft(
            source_id="sec_edgar",
            symbol_universe_id=universe_id,
            fact_kind="fundamental.eps",
            effective_from=T1,
            recorded_from=T1,
            source_url="",  # empty -> CHECK length > 0 rejects.
            retrieval_method="api",
            retrieved_at=T1,
            value_numeric=Decimal("1.0"),
        ).with_payload(b'{"raw": "ok"}')
        with pytest.raises(MissingProvenanceError):
            await repository.insert_fact(bad)


@pytest.mark.asyncio
async def test_insert_with_invalid_retrieval_method_raises(
    seeded_world: dict[str, Any],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]

    async with with_tenant_context(tenant_id):
        bad = ResearchFactDraft(
            source_id="sec_edgar",
            symbol_universe_id=universe_id,
            fact_kind="fundamental.eps",
            effective_from=T1,
            recorded_from=T1,
            source_url="https://example.test/x.json",
            retrieval_method="screenshot",  # not in the allowed enum.
            retrieved_at=T1,
            value_numeric=Decimal("1.0"),
        ).with_payload(b'{"raw": "ok"}')
        with pytest.raises(MissingProvenanceError):
            await repository.insert_fact(bad)


@pytest.mark.asyncio
async def test_insert_with_no_value_field_raises(
    seeded_world: dict[str, Any],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]

    async with with_tenant_context(tenant_id):
        bad = ResearchFactDraft(
            source_id="sec_edgar",
            symbol_universe_id=universe_id,
            fact_kind="fundamental.eps",
            effective_from=T1,
            recorded_from=T1,
            source_url="https://example.test/x.json",
            retrieval_method="api",
            retrieved_at=T1,
            # All three value_* fields NULL -> CHECK rejects.
        ).with_payload(b'{"raw": "ok"}')
        with pytest.raises(MissingProvenanceError):
            await repository.insert_fact(bad)


@pytest.mark.asyncio
async def test_insert_with_effective_from_after_effective_to_raises(
    seeded_world: dict[str, Any],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]
    earlier = T1
    later = datetime(2024, 4, 26, 10, 0, 0, tzinfo=UTC)

    async with with_tenant_context(tenant_id):
        bad = ResearchFactDraft(
            source_id="sec_edgar",
            symbol_universe_id=universe_id,
            fact_kind="fundamental.eps",
            effective_from=later,
            effective_to=earlier,  # later -> earlier -> CHECK rejects.
            recorded_from=T1,
            source_url="https://example.test/x.json",
            retrieval_method="api",
            retrieved_at=T1,
            value_numeric=Decimal("1.0"),
        ).with_payload(b'{"raw": "ok"}')
        with pytest.raises(MissingProvenanceError):
            await repository.insert_fact(bad)


@pytest.mark.asyncio
async def test_missing_provenance_error_carries_canonical_type_uri(
    seeded_world: dict[str, Any],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """The lifted error renders the canonical ``urn:`` type + 422 status."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]

    async with with_tenant_context(tenant_id):
        bad = ResearchFactDraft(
            source_id="sec_edgar",
            symbol_universe_id=universe_id,
            fact_kind="fundamental.eps",
            effective_from=T1,
            recorded_from=T1,
            source_url="",
            retrieval_method="api",
            retrieved_at=T1,
            value_numeric=Decimal("1.0"),
        ).with_payload(b'{"raw": "ok"}')
        with pytest.raises(MissingProvenanceError) as excinfo:
            await repository.insert_fact(bad)

    problem = excinfo.value.to_problem_dict()
    assert problem["type"] == "urn:iguanatrader:error:missing-provenance"
    assert problem["status"] == 422
    assert "research_facts insert" in (problem.get("detail") or "")


# ---------------------------------------------------------------------------
# Hybrid payload constraints (CHECK XOR + size tier)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_with_payload_small_yields_inline(
    seeded_world: dict[str, Any],
) -> None:
    """``with_payload(<8000 bytes>)`` populates ``raw_payload_inline`` only."""
    raw = b'{"x": "y"}' * 800  # well under 16384.
    base = ResearchFactDraft(
        source_id="sec_edgar",
        fact_kind="fundamental.eps",
        effective_from=T1,
        recorded_from=T1,
        source_url="https://example.test/x.json",
        retrieval_method="api",
        retrieved_at=T1,
        value_numeric=Decimal("1.0"),
    )
    drafted = base.with_payload(raw)

    assert drafted.raw_payload_inline is not None
    assert drafted.raw_payload_path is None
    assert drafted.raw_payload_sha256 is None
    assert drafted.raw_payload_size_bytes == len(raw)


@pytest.mark.asyncio
async def test_with_payload_large_persists_to_filesystem(
    seeded_world: dict[str, Any],
    with_session: AsyncSession,
    repository: ResearchRepository,
    tmp_path: Any,
) -> None:
    """``insert_fact`` writes a >16KB payload under the canonical path."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]

    big = b'{"data": "x"}' * 4000  # > 16384 bytes (~52000).
    sha256 = hashlib.sha256(big).hexdigest()

    base = ResearchFactDraft(
        source_id="sec_edgar",
        symbol_universe_id=universe_id,
        fact_kind="fundamental.eps",
        effective_from=T1,
        recorded_from=T1,
        source_url="https://example.test/x.json",
        retrieval_method="scrape",
        retrieved_at=T1,
        value_numeric=Decimal("1.0"),
    ).with_payload(big)

    assert base.raw_payload_size_bytes == len(big)
    assert base.raw_payload_sha256 == sha256
    assert base.raw_payload_inline is None

    async with with_tenant_context(tenant_id):
        inserted = await repository.insert_fact(base)
        await with_session.commit()

    expected_dir = tmp_path / "cache" / "sec_edgar" / T1.strftime("%Y-%m")
    expected_file = expected_dir / f"{sha256}.json"
    assert expected_file.exists()
    assert expected_file.read_bytes() == big
    assert inserted.raw_payload_path == f"sec_edgar/{T1.strftime('%Y-%m')}/{sha256}.json"
    assert inserted.raw_payload_sha256 == sha256
    assert inserted.raw_payload_size_bytes == len(big)


@pytest.mark.asyncio
async def test_payload_xor_check_rejects_both_set(
    seeded_world: dict[str, Any],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """Setting both inline + path simultaneously trips the XOR CHECK."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]

    async with with_tenant_context(tenant_id):
        bad = ResearchFactDraft(
            source_id="sec_edgar",
            symbol_universe_id=universe_id,
            fact_kind="fundamental.eps",
            effective_from=T1,
            recorded_from=T1,
            source_url="https://example.test/x.json",
            retrieval_method="api",
            retrieved_at=T1,
            value_numeric=Decimal("1.0"),
            raw_payload_inline={"a": 1},
            raw_payload_path="sec_edgar/2024-04/abc.json",
            raw_payload_sha256="0" * 64,
            raw_payload_size_bytes=8000,
        )
        with pytest.raises(MissingProvenanceError):
            await repository.insert_fact(bad)


@pytest.mark.asyncio
async def test_payload_path_without_sha256_rejected(
    seeded_world: dict[str, Any],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """``raw_payload_path`` set with NULL ``raw_payload_sha256`` → CHECK rejects."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]

    async with with_tenant_context(tenant_id):
        bad = ResearchFactDraft(
            source_id="sec_edgar",
            symbol_universe_id=universe_id,
            fact_kind="fundamental.eps",
            effective_from=T1,
            recorded_from=T1,
            source_url="https://example.test/x.json",
            retrieval_method="api",
            retrieved_at=T1,
            value_numeric=Decimal("1.0"),
            raw_payload_inline=None,
            raw_payload_path="sec_edgar/2024-04/abc.json",
            raw_payload_sha256=None,
            raw_payload_size_bytes=20000,
        )
        with pytest.raises(MissingProvenanceError):
            await repository.insert_fact(bad)


@pytest.mark.asyncio
async def test_payload_inline_with_size_over_threshold_rejected(
    seeded_world: dict[str, Any],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """``raw_payload_size_bytes >= 16384`` with NULL path → CHECK rejects."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]

    async with with_tenant_context(tenant_id):
        # Set inline + size declares > threshold + path NULL -> tier
        # consistency CHECK rejects.
        bad = ResearchFactDraft(
            source_id="sec_edgar",
            symbol_universe_id=universe_id,
            fact_kind="fundamental.eps",
            effective_from=T1,
            recorded_from=T1,
            source_url="https://example.test/x.json",
            retrieval_method="api",
            retrieved_at=T1,
            value_numeric=Decimal("1.0"),
            raw_payload_inline={"a": 1},
            raw_payload_path=None,
            raw_payload_sha256=None,
            raw_payload_size_bytes=PAYLOAD_INLINE_THRESHOLD + 100,
        )
        with pytest.raises(MissingProvenanceError):
            await repository.insert_fact(bad)


# ---------------------------------------------------------------------------
# Append-only L1 (ORM listener) + L2 (DB triggers)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orm_update_on_research_fact_blocked_by_l1(
    seeded_world: dict[str, Any],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """Mutating an ORM-loaded :class:`ResearchFact` raises before driver SQL."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]

    async with with_tenant_context(tenant_id):
        await repository.insert_fact(_valid_draft(source_id="sec_edgar", universe_id=universe_id))
        await with_session.commit()

        loaded = (await with_session.execute(select(ResearchFact))).scalar_one()
        loaded.value_numeric = Decimal("99.0")
        with pytest.raises(AppendOnlyViolationError):
            await with_session.flush()


@pytest.mark.asyncio
async def test_raw_sql_delete_on_research_briefs_blocked_by_l2(
    seeded_world: dict[str, Any],
    with_session: AsyncSession,
) -> None:
    """Raw SQL DELETE on ``research_briefs`` is rejected by the L2 trigger.

    No row needs to exist for the trigger to fire — SQLite's BEFORE DELETE
    fires on every DELETE statement that targets the table, regardless of
    whether the WHERE clause matches anything. We exercise this without
    populating a row to avoid the foreign-key dance for ``watchlist_configs``.
    """
    tenant_id = seeded_world["tenant_id"]

    async with with_tenant_context(tenant_id):
        with pytest.raises(DBAPIError):
            # The trigger's RAISE(FAIL, ...) surfaces as DBAPIError; the
            # exact subtype is sqlalchemy.exc.OperationalError on aiosqlite.
            await with_session.execute(
                text("DELETE FROM research_briefs WHERE id = :id"),
                {"id": str(uuid4())},
            )


@pytest.mark.asyncio
async def test_supersede_recorded_to_permitted_by_narrow_trigger_exception(
    seeded_world: dict[str, Any],
    with_session: AsyncSession,
    repository: ResearchRepository,
) -> None:
    """:meth:`supersede_fact` succeeds — its raw-SQL UPDATE matches the exception."""
    universe_id = seeded_world["universe_id"]
    tenant_id = seeded_world["tenant_id"]
    later = datetime(2024, 4, 26, 10, 0, 0, tzinfo=UTC)

    async with with_tenant_context(tenant_id):
        inserted = await repository.insert_fact(
            _valid_draft(source_id="sec_edgar", universe_id=universe_id)
        )
        await with_session.commit()

        # Should NOT raise — the L2 trigger's WHEN clause permits the
        # NULL -> non-NULL transition on recorded_to.
        await repository.supersede_fact(inserted.id, later)
        await with_session.commit()

        # Re-read directly via raw SQL to confirm the update landed.
        row = (
            await with_session.execute(
                text("SELECT recorded_to FROM research_facts WHERE id = :id"),
                {"id": str(inserted.id)},
            )
        ).first()
        assert row is not None
        assert row[0] is not None
