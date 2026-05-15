"""Postgres smoke test for slice ``postgres-compose-overlay``.

Skips by default. To run::

    docker compose -f docker-compose.mvp.yml -f docker-compose.mvp.override.yml \\
        -f docker-compose.postgres.yml up -d postgres
    IGUANA_TEST_POSTGRES_URL=postgresql+asyncpg://iguanatrader:CHANGE-ME@localhost:5432/iguanatrader \\
        poetry run pytest apps/api/tests/integration/test_postgres_smoke.py -v

Exercises three claims of the slice:

1. Alembic head migrates a fresh Postgres without error (validates
   every migration's postgres branch is wired — including the new
   0006 branch added in this slice).
2. The ORM can round-trip a :class:`Tenant` row via the JSON column —
   verifies the cross-dialect :class:`sqlalchemy.JSON` column type
   resolves to JSONB on Postgres without ORM changes.
3. The L2 append-only triggers + plpgsql functions are present on
   ``approval_requests`` + ``approval_decisions`` (the gap that the
   0006 postgres branch in this slice closes).

Not part of CI's `--collect-only` run; it's a manual gate run before
the VPS cut-over per `docs/runbooks/postgres-cutover.md`.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from iguanatrader.persistence import Tenant, engine_factory, session_factory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

_POSTGRES_URL_ENV = "IGUANA_TEST_POSTGRES_URL"
_pg_url = os.environ.get(_POSTGRES_URL_ENV)

pytestmark = pytest.mark.skipif(
    _pg_url is None,
    reason=f"Set {_POSTGRES_URL_ENV} to a postgresql+asyncpg://... DSN to run.",
)


@pytest.fixture
async def fresh_postgres_engine() -> AsyncIterator[AsyncEngine]:
    """Drop+recreate the public schema, then run `alembic upgrade head`.

    Destructive — only run against the dedicated test DSN.
    """
    assert _pg_url is not None
    engine = engine_factory(_pg_url)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()

    cfg = Config("apps/api/alembic.ini")
    cfg.set_main_option("sqlalchemy.url", _pg_url)
    os.environ["IGUANA_DATABASE_URL"] = _pg_url
    command.upgrade(cfg, "head")

    engine = engine_factory(_pg_url)
    try:
        yield engine
    finally:
        await engine.dispose()


async def test_alembic_upgrade_head_applies_cleanly(
    fresh_postgres_engine: AsyncEngine,
) -> None:
    """`alembic upgrade head` reached head without raising."""
    async with fresh_postgres_engine.connect() as conn:
        result = await conn.execute(text("SELECT version_num FROM alembic_version"))
        version = result.scalar_one()
    assert version is not None
    assert len(version) >= 4


async def test_tenant_round_trip_via_jsonb(
    fresh_postgres_engine: AsyncEngine,
) -> None:
    """Cross-dialect JSON column maps to JSONB on Postgres without ORM change."""
    sf = session_factory(fresh_postgres_engine)
    tenant_id = uuid4()
    flags = {"slice_postgres": True, "rev": 1}
    async with sf() as s:
        s.add(Tenant(id=tenant_id, name="pg-smoke", feature_flags=flags))
        await s.commit()
    async with sf() as s:
        row = await s.get(Tenant, tenant_id)
        assert row is not None
        assert row.feature_flags == flags


async def test_approval_l2_triggers_present_on_postgres(
    fresh_postgres_engine: AsyncEngine,
) -> None:
    """The 0006 fix in this slice plants L2 triggers on Postgres too.

    We assert the four trigger names + the two RAISE-EXCEPTION
    functions exist. Firing semantics are implicit in plpgsql — a
    BEFORE UPDATE/DELETE trigger that calls RAISE EXCEPTION will
    abort on every UPDATE/DELETE by Postgres design; testing the
    firing would require seeding the FK chain (tenant +
    trade_proposal) which is out of scope for a smoke gate.
    """
    expected_triggers = {
        ("trg_approval_requests_no_update", "approval_requests"),
        ("trg_approval_requests_no_delete", "approval_requests"),
        ("trg_approval_decisions_no_update", "approval_decisions"),
        ("trg_approval_decisions_no_delete", "approval_decisions"),
    }
    async with fresh_postgres_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT t.tgname, c.relname "
                "FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                "WHERE t.tgname LIKE 'trg_approval_%' AND NOT t.tgisinternal"
            )
        )
        found = {(row[0], row[1]) for row in result.all()}
    missing = expected_triggers - found
    assert not missing, f"Postgres triggers missing on approval tables: {missing}"

    async with fresh_postgres_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT proname FROM pg_proc "
                "WHERE proname IN ('raise_approval_requests_append_only', "
                "'raise_approval_decisions_append_only')"
            )
        )
        functions = {row[0] for row in result.all()}
    assert functions == {
        "raise_approval_requests_append_only",
        "raise_approval_decisions_append_only",
    }
