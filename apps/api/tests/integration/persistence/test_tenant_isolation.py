"""Tenant isolation — auto-filter SELECT + auto-stamp INSERT + mismatch reject.

Covers spec scenarios under "Tenant-scoped Select queries SHALL be auto-filtered"
and "Inserts under tenant context SHALL stamp tenant_id automatically".
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from iguanatrader.persistence.base import Base
from iguanatrader.persistence.errors import (
    TenantContextMismatchError,
    TenantContextMissingError,
)
from iguanatrader.shared.contextvars import with_tenant_context
from sqlalchemy import Uuid, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column


class _ScopedFoo(Base):
    """Tenant-scoped test model. Inherits __tenant_scoped__ = True from Base."""

    __tablename__ = "_test_scoped_foo"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    label: Mapped[str]


class _GlobalCatalogue(Base):
    """Cross-tenant catalogue (opt out via class attribute)."""

    __tablename__ = "_test_global_catalogue"
    __tenant_scoped__ = False

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str]


@pytest.mark.asyncio
async def test_select_returns_only_current_tenant_rows(
    session_factory_fx: async_sessionmaker[AsyncSession],
) -> None:
    tenant_a = uuid4()
    tenant_b = uuid4()

    async with with_tenant_context(tenant_a), session_factory_fx() as s:
        s.add(_ScopedFoo(id=uuid4(), label="from-a"))
        await s.commit()

    async with with_tenant_context(tenant_b), session_factory_fx() as s:
        s.add(_ScopedFoo(id=uuid4(), label="from-b"))
        await s.commit()

    async with with_tenant_context(tenant_a), session_factory_fx() as s:
        rows = (await s.execute(select(_ScopedFoo))).scalars().all()
        assert len(rows) == 1
        assert rows[0].label == "from-a"
        assert rows[0].tenant_id == tenant_a


@pytest.mark.asyncio
async def test_select_without_tenant_context_raises(
    session_factory_fx: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory_fx() as s:
        with pytest.raises(TenantContextMissingError):
            await s.execute(select(_ScopedFoo))


@pytest.mark.asyncio
async def test_select_against_opt_out_table_skips_tenant_filter(
    session_factory_fx: async_sessionmaker[AsyncSession],
) -> None:
    """Cross-tenant catalogues (e.g. research_sources) are not filtered."""
    tenant = uuid4()
    other_tenant = uuid4()

    # Insert from tenant A perspective into the catalogue (no tenant_id column).
    async with with_tenant_context(tenant), session_factory_fx() as s:
        s.add(_GlobalCatalogue(id=uuid4(), name="entry-1"))
        s.add(_GlobalCatalogue(id=uuid4(), name="entry-2"))
        await s.commit()

    # Tenant B sees the same catalogue rows (no filter applied).
    async with with_tenant_context(other_tenant), session_factory_fx() as s:
        rows = (await s.execute(select(_GlobalCatalogue))).scalars().all()
        assert {r.name for r in rows} == {"entry-1", "entry-2"}


@pytest.mark.asyncio
async def test_insert_without_explicit_tenant_id_is_stamped_from_context(
    session_factory_fx: async_sessionmaker[AsyncSession],
) -> None:
    tenant = uuid4()
    pk = uuid4()

    async with with_tenant_context(tenant), session_factory_fx() as s:
        # tenant_id intentionally NOT set on the instance.
        instance = _ScopedFoo(id=pk, label="auto-stamped")
        s.add(instance)
        await s.commit()
        assert instance.tenant_id == tenant


@pytest.mark.asyncio
async def test_insert_with_mismatched_explicit_tenant_id_is_rejected(
    session_factory_fx: async_sessionmaker[AsyncSession],
) -> None:
    tenant_a = uuid4()
    tenant_b = uuid4()

    async with with_tenant_context(tenant_a), session_factory_fx() as s:
        s.add(_ScopedFoo(id=uuid4(), tenant_id=tenant_b, label="cross-tenant-attempt"))
        with pytest.raises(TenantContextMismatchError):
            await s.flush()


@pytest.mark.asyncio
async def test_insert_without_tenant_context_raises(
    session_factory_fx: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory_fx() as s:
        s.add(_ScopedFoo(id=uuid4(), label="no-context"))
        with pytest.raises(TenantContextMissingError):
            await s.flush()


@pytest.mark.asyncio
async def test_tenant_var_propagates_through_sequential_async_writes(
    session_factory_fx: async_sessionmaker[AsyncSession],
) -> None:
    """ContextVar must propagate across awaits.

    Sequential rather than gather() because SQLite + multi-connection concurrent
    writes are flaky under WAL contention even with busy_timeout. Production
    runs Postgres in v1.5; the sequential version is sufficient to prove
    ``with_tenant_context`` carries through await boundaries.
    """
    tenant_a = uuid4()
    tenant_b = uuid4()

    async def _write(tenant: UUID, label: str) -> None:
        async with with_tenant_context(tenant), session_factory_fx() as s:
            s.add(_ScopedFoo(id=uuid4(), label=label))
            await s.commit()

    await _write(tenant_a, "seq-a")
    await _write(tenant_b, "seq-b")

    async with with_tenant_context(tenant_a), session_factory_fx() as s:
        rows = (await s.execute(select(_ScopedFoo))).scalars().all()
        assert {r.label for r in rows} == {"seq-a"}
