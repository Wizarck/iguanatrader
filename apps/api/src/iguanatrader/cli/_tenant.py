"""Tenant-resolution helper shared across CLI subcommands (slice T4).

Extracted from `cli/research.py` so any subcommand needing
single-tenant defaulting (research, trading, future ones) can import
from one canonical location.
"""

from __future__ import annotations

import os
from uuid import UUID

import typer

_DEFAULT_DB_URL = "sqlite+aiosqlite:///./data/iguanatrader.db"


def db_url() -> str:
    """Resolve the operator-side DB URL from env, with a sensible default."""
    return os.getenv("IGUANA_DATABASE_URL") or _DEFAULT_DB_URL


async def resolve_tenant_id(tenant: str | None) -> UUID:
    """Resolve a tenant slug → UUID; default to first tenant if None.

    Single-tenant deployments need no flag. Multi-tenant deployments
    pass `--tenant <slug>`. Exits with code 1 + a typer.echo'd error
    message if the slug is unknown.
    """
    from sqlalchemy import select

    from iguanatrader.persistence import Tenant, engine_factory, session_factory

    engine = engine_factory(db_url())
    try:
        sessionmaker = session_factory(engine)
        async with sessionmaker() as session:
            stmt = select(Tenant)
            if tenant is not None:
                stmt = stmt.where(Tenant.name == tenant)
            result = await session.execute(stmt)
            row = result.scalars().first()
    finally:
        await engine.dispose()
    if row is None:
        typer.echo(f"No tenant found (name={tenant!r})")
        raise typer.Exit(code=1)
    return row.id


__all__ = ["db_url", "resolve_tenant_id"]
