"""Hypothesis: tenant filter invariant holds for arbitrary insert/select sequences.

Spec scenario: "Hypothesis finds no counterexample across 50 examples" — the
listener-injected ``WHERE tenant_id = :current`` MUST hold for every Select
under any tenant present in the sequence, regardless of insert order, mix, or
session lifecycle.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import UUID, uuid4

# Slice 2 gotcha: Hypothesis + asyncio.run on Windows leaks file descriptors
# under filterwarnings=["error"] when the default ProactorEventLoop is used.
# The selector loop is the safe choice for SQLite-on-aiosqlite tests.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from iguanatrader.persistence import (
    engine_factory,
    register_global_listeners,
    session_factory,
    unregister_global_listeners,
)
from iguanatrader.persistence.base import Base
from iguanatrader.shared.contextvars import with_tenant_context
from sqlalchemy import Uuid, select
from sqlalchemy.orm import Mapped, mapped_column


class _PropFoo(Base):
    __tablename__ = "_test_prop_foo"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    label: Mapped[str]


# A small fixed pool of tenant UUIDs so Hypothesis can re-use them across
# inserts and queries (otherwise every example uses unique tenants and the
# property reduces to "an empty filter returns nothing", which is trivial).
_TENANT_POOL = [uuid4() for _ in range(4)]


def _setup_engine(tmp_path: Path) -> tuple:
    """Create a per-example engine + sessionmaker with schema."""
    db_path = tmp_path / "ig_property.db"
    engine = engine_factory(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    return engine, session_factory(engine)


@settings(
    max_examples=50,
    deadline=2000,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    operations=st.lists(
        st.tuples(
            st.sampled_from(_TENANT_POOL),
            st.text(min_size=1, max_size=20),
        ),
        min_size=1,
        max_size=15,
    ),
)
def test_select_under_tenant_returns_only_that_tenant_rows(
    tmp_path_factory: pytest.TempPathFactory,
    operations: list[tuple[UUID, str]],
) -> None:
    """For any insert sequence, every Select under tenant X returns ONLY X-rows."""

    async def _run() -> None:
        register_global_listeners()
        try:
            tmp_path = tmp_path_factory.mktemp("ig_prop")
            engine, sf = _setup_engine(tmp_path)
            try:
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)

                # Phase 1: insert each (tenant, label) under its tenant context.
                for tenant, label in operations:
                    async with with_tenant_context(tenant), sf() as s:
                        s.add(_PropFoo(id=uuid4(), label=label))
                        await s.commit()

                # Phase 2: for each tenant present, the Select must return ONLY
                # that tenant's rows (verified row-by-row).
                tenants_present = {t for t, _ in operations}
                for tenant in tenants_present:
                    async with with_tenant_context(tenant), sf() as s:
                        rows = (await s.execute(select(_PropFoo))).scalars().all()
                        for row in rows:
                            assert row.tenant_id == tenant, (
                                f"Cross-tenant leak: row {row.id} owned by "
                                f"{row.tenant_id} returned under tenant {tenant}"
                            )
                        # Count check: row count under tenant X equals the number
                        # of insert operations targeting X.
                        expected = sum(1 for t, _ in operations if t == tenant)
                        assert (
                            len(rows) == expected
                        ), f"Tenant {tenant}: expected {expected} rows, got {len(rows)}"

                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.drop_all)
            finally:
                await engine.dispose()
        finally:
            unregister_global_listeners()

    asyncio.run(_run())
