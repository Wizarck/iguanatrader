"""Admin operator commands — ``iguanatrader admin <subcommand>``.

Subcommands:

* ``bootstrap-tenant`` — create the first tenant + admin user on a
  fresh database. Idempotent on the tenant slug + user email pair
  (re-running with the same slug fails unless ``--force-reset`` is
  passed, which deletes the row first).

The auth route :mod:`iguanatrader.api.routes.auth` raises
:class:`BootstrapNotReadyError` when the database has zero tenants and
the error message explicitly points operators at this command.
"""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import typer

app: typer.Typer = typer.Typer(
    name="admin",
    help="Admin commands (tenant bootstrap, etc.).",
    no_args_is_help=True,
)

_DEFAULT_DB_URL = "sqlite+aiosqlite:///./data/iguanatrader.db"


def _db_url() -> str:
    return os.getenv("IGUANA_DATABASE_URL") or _DEFAULT_DB_URL


@app.command("bootstrap-tenant")
def bootstrap_tenant(
    slug: str = typer.Argument(
        ...,
        help="Tenant slug (also stored as Tenant.name). Lowercase + hyphens.",
    ),
    email: str = typer.Option(
        ...,
        "--email",
        "-e",
        help="Admin user email address.",
    ),
    password: str = typer.Option(
        ...,
        "--password",
        "-p",
        prompt=True,
        hide_input=True,
        confirmation_prompt=False,
        help=(
            "Admin user plaintext password. Hashed with Argon2id before "
            "insert. Prompted (no echo) if not passed via flag."
        ),
    ),
    force_reset: bool = typer.Option(
        False,
        "--force-reset",
        help=(
            "If the tenant slug exists, delete it (and its users) before "
            "re-creating. Destroys data; only use on a brand-new DB."
        ),
    ),
) -> None:
    """Create the first tenant + admin user on a fresh database.

    Usage:

        iguanatrader admin bootstrap-tenant arturo-trading \\
            --email arturo@example.com --password 'changeme-2026'

    Exits with code 0 on success, non-zero on validation failure or
    duplicate-slug-without-force-reset.
    """
    asyncio.run(_bootstrap_tenant_async(slug, email, password, force_reset))


async def _bootstrap_tenant_async(
    slug: str,
    email: str,
    password: str,
    force_reset: bool,
) -> None:
    """Async body of the ``bootstrap-tenant`` command."""
    # Local imports keep ``--help`` fast (gotcha #29).
    from sqlalchemy import delete, select

    from iguanatrader.api.auth import hash_password
    from iguanatrader.persistence import (
        Tenant,
        User,
        engine_factory,
        session_factory,
    )
    from iguanatrader.shared.contextvars import with_tenant_context

    engine = engine_factory(_db_url())
    try:
        sessionmaker = session_factory(engine)

        async with sessionmaker() as session:
            existing = await session.execute(select(Tenant).where(Tenant.name == slug))
            existing_tenant = existing.scalars().first()
            if existing_tenant is not None:
                if not force_reset:
                    typer.echo(
                        f"ERROR: tenant {slug!r} already exists (id={existing_tenant.id}). "
                        "Pass --force-reset to delete + re-create."
                    )
                    raise typer.Exit(code=1)
                # --force-reset: drop the existing tenant's users + the
                # tenant itself. We do this with raw deletes inside a
                # with_tenant_context to satisfy the slice-3 listener.
                async with with_tenant_context(existing_tenant.id):
                    await session.execute(delete(User).where(User.tenant_id == existing_tenant.id))
                    await session.execute(delete(Tenant).where(Tenant.id == existing_tenant.id))
                    await session.commit()
                typer.echo(
                    f"--force-reset: deleted tenant {slug!r} (id={existing_tenant.id}) + its users."
                )

        tenant_id = uuid4()
        user_id = uuid4()
        hashed = hash_password(password)

        async with sessionmaker() as session:
            session.add(Tenant(id=tenant_id, name=slug, feature_flags={}))
            await session.commit()

        async with with_tenant_context(tenant_id), sessionmaker() as session:
            session.add(
                User(
                    id=user_id,
                    tenant_id=tenant_id,
                    email=email,
                    password_hash=hashed,
                    role="tenant_user",
                )
            )
            await session.commit()
    finally:
        await engine.dispose()

    typer.echo(f"OK — tenant_id={tenant_id} user_id={user_id} email={email} slug={slug}")


__all__ = ["app"]
