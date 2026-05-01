"""Append-only invariant — INSERT OK, UPDATE/DELETE blocked at flush.

Covers spec scenarios under "Append-only tables SHALL reject UPDATE and DELETE
at flush time". The L2 trigger layer (DB-level RAISE on UPDATE/DELETE) ships
per-table in consuming slices (O1 audit_log, P1 approval_decisions, etc.); the
test for that L2 path lives in those slices.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import Uuid, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from iguanatrader.persistence.base import Base
from iguanatrader.persistence.errors import AppendOnlyViolationError
from iguanatrader.shared.contextvars import with_tenant_context


class _AppendOnlyRow(Base):
    """Append-only test model. Tenant-scoped + append-only."""

    __tablename__ = "_test_append_only_row"
    __tablename_is_append_only__ = True

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    payload: Mapped[str]


@pytest.mark.asyncio
async def test_insert_into_append_only_table_succeeds(
    session_factory_fx: async_sessionmaker[AsyncSession],
) -> None:
    tenant = uuid4()

    async with with_tenant_context(tenant), session_factory_fx() as s:
        s.add(_AppendOnlyRow(id=uuid4(), payload="event-1"))
        s.add(_AppendOnlyRow(id=uuid4(), payload="event-2"))
        await s.commit()

    async with with_tenant_context(tenant), session_factory_fx() as s:
        rows = (await s.execute(select(_AppendOnlyRow))).scalars().all()
        assert {r.payload for r in rows} == {"event-1", "event-2"}


@pytest.mark.asyncio
async def test_update_on_append_only_row_raises_before_db(
    session_factory_fx: async_sessionmaker[AsyncSession],
) -> None:
    tenant = uuid4()
    pk = uuid4()

    async with with_tenant_context(tenant), session_factory_fx() as s:
        s.add(_AppendOnlyRow(id=pk, payload="original"))
        await s.commit()

    # Attempt UPDATE via ORM — listener should raise before driver SQL.
    async with with_tenant_context(tenant), session_factory_fx() as s:
        loaded = (
            await s.execute(select(_AppendOnlyRow).where(_AppendOnlyRow.id == pk))
        ).scalar_one()
        loaded.payload = "tampered"
        with pytest.raises(AppendOnlyViolationError, match="UPDATE on _test_append_only_row"):
            await s.flush()

    # Verify the row in the database is unchanged via a fresh session.
    async with with_tenant_context(tenant), session_factory_fx() as s:
        row = (
            await s.execute(select(_AppendOnlyRow).where(_AppendOnlyRow.id == pk))
        ).scalar_one()
        assert row.payload == "original"


@pytest.mark.asyncio
async def test_delete_on_append_only_row_raises_before_db(
    session_factory_fx: async_sessionmaker[AsyncSession],
) -> None:
    tenant = uuid4()
    pk = uuid4()

    async with with_tenant_context(tenant), session_factory_fx() as s:
        s.add(_AppendOnlyRow(id=pk, payload="cannot-delete"))
        await s.commit()

    async with with_tenant_context(tenant), session_factory_fx() as s:
        loaded = (
            await s.execute(select(_AppendOnlyRow).where(_AppendOnlyRow.id == pk))
        ).scalar_one()
        await s.delete(loaded)
        with pytest.raises(AppendOnlyViolationError, match="DELETE on _test_append_only_row"):
            await s.flush()

    # Verify the row is still queryable.
    async with with_tenant_context(tenant), session_factory_fx() as s:
        rows = (await s.execute(select(_AppendOnlyRow))).scalars().all()
        assert len(rows) == 1
        assert rows[0].payload == "cannot-delete"
