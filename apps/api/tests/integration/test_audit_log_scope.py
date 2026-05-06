"""Integration tests for audit_log per-tenant + cross-tenant scope (design D8).

Test matrix (per task 7.5):

- System actor inserts ``tenant_id IS NULL`` row (no error).
- Tenant-context query filters per-tenant only.
- System-context query (``tenant_id_var`` unset) returns NULL-tenant rows.
- UPDATE / DELETE on ``audit_log`` rejected by append_only_listener.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from iguanatrader.contexts.observability.models import AuditLog
from iguanatrader.persistence import Tenant
from iguanatrader.persistence.errors import AppendOnlyViolationError
from iguanatrader.shared.contextvars import (
    session_var,
    with_tenant_context,
)
from iguanatrader.shared.time import now
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
async def session_for_test(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with schema_session_factory() as session:
        token = session_var.set(session)
        try:
            yield session
        finally:
            session_var.reset(token)


@pytest.fixture
async def two_tenants(
    schema_session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID]:
    a = uuid4()
    b = uuid4()
    async with schema_session_factory() as s:
        s.add(Tenant(id=a, name="tenant-a", feature_flags={}))
        s.add(Tenant(id=b, name="tenant-b", feature_flags={}))
        await s.commit()
    return a, b


async def test_system_actor_inserts_null_tenant_row(
    session_for_test: AsyncSession,
) -> None:
    """``tenant_id_var`` unset + ``tenant_id=None`` writes a global row."""
    entry = AuditLog(
        id=uuid4(),
        tenant_id=None,
        actor_kind="system",
        event="ops.gitleaks.failure",
        metadata_json={"detail": "scrubbed"},
    )
    session_for_test.add(entry)
    await session_for_test.commit()

    # Read back via query_global — listener must allow with tenant_id_var unset.
    rows = (
        (await session_for_test.execute(select(AuditLog).where(AuditLog.tenant_id.is_(None))))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].event == "ops.gitleaks.failure"


async def test_tenant_context_query_filters_to_per_tenant(
    session_for_test: AsyncSession,
    two_tenants: tuple[UUID, UUID],
) -> None:
    a, b = two_tenants
    async with with_tenant_context(a):
        entry_a = AuditLog(
            id=uuid4(),
            tenant_id=a,
            actor_kind="user",
            event="auth.login.success",
        )
        session_for_test.add(entry_a)
        await session_for_test.commit()

    async with with_tenant_context(b):
        entry_b = AuditLog(
            id=uuid4(),
            tenant_id=b,
            actor_kind="user",
            event="auth.login.success",
        )
        session_for_test.add(entry_b)
        await session_for_test.commit()

    # In tenant a's context, only a's audit_log rows are visible.
    async with with_tenant_context(a):
        rows = (await session_for_test.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].tenant_id == a


async def test_update_on_audit_log_blocked_by_append_only_listener(
    session_for_test: AsyncSession,
) -> None:
    entry = AuditLog(
        id=uuid4(),
        tenant_id=None,
        actor_kind="system",
        event="ops.first",
    )
    session_for_test.add(entry)
    await session_for_test.commit()

    entry.event = "ops.mutated"
    with pytest.raises(AppendOnlyViolationError):
        await session_for_test.commit()


async def test_delete_on_audit_log_blocked_by_append_only_listener(
    session_for_test: AsyncSession,
) -> None:
    entry = AuditLog(
        id=uuid4(),
        tenant_id=None,
        actor_kind="system",
        event="ops.first",
    )
    session_for_test.add(entry)
    await session_for_test.commit()

    await session_for_test.delete(entry)
    with pytest.raises(AppendOnlyViolationError):
        await session_for_test.commit()


# Suppress unused warning for `now` / `timedelta` reserved for time-window
# follow-up tests (slice O2).
_ = (now, timedelta)
