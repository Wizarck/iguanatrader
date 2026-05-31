"""Admin operator commands — ``iguanatrader admin <subcommand>``.

Subcommands:

* ``bootstrap-tenant`` — create the first tenant + admin user on a
  fresh database. Idempotent on the tenant slug + user email pair
  (re-running with the same slug fails unless ``--force-reset`` is
  passed, which deletes the row first).
* ``register-symbol`` — register a ticker in the tenant's
  ``symbol_universe`` + ``watchlist_configs`` tables so research-brief
  refresh can resolve its FKs. Without this, ``POST
  /api/v1/research/briefs/{symbol}/refresh`` raises ``LookupError``
  (surfaced as 404 by the route).

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

        # #16: create the Tenant AND its admin User in ONE transaction. The
        # previous two-commit version could crash after committing the
        # tenant but before the user, leaving an orphaned tenant with no
        # admin — a permanent lockout (login impossible, and a re-run of
        # bootstrap refuses because the tenant already exists). SQLAlchemy
        # orders the inserts by the User→Tenant FK, so a single commit is
        # safe; a failure rolls back both.
        async with with_tenant_context(tenant_id), sessionmaker() as session:
            session.add(Tenant(id=tenant_id, name=slug, feature_flags={}))
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


_METHODOLOGY_CHOICES = ("three_pillar", "canslim", "magic_formula", "qarp", "multi_factor")
_TIER_CHOICES = ("primary", "secondary")
_SCHEDULE_CHOICES = ("daily", "weekly", "manual")


@app.command("register-symbol")
def register_symbol(
    symbol: str = typer.Argument(
        ...,
        help="Ticker symbol (e.g. NVDA). Stored verbatim — uppercase recommended.",
    ),
    tenant: str = typer.Option(
        ...,
        "--tenant",
        "-t",
        help="Tenant slug (matches Tenant.name from bootstrap-tenant).",
    ),
    exchange: str = typer.Option(
        "NASDAQ",
        "--exchange",
        "-x",
        help="Exchange code. Free-form text; default NASDAQ.",
    ),
    tier: str = typer.Option(
        "primary",
        "--tier",
        help=f"Watchlist tier. One of: {', '.join(_TIER_CHOICES)}.",
    ),
    methodology: str = typer.Option(
        "three_pillar",
        "--methodology",
        "-m",
        help=f"Default brief methodology. One of: {', '.join(_METHODOLOGY_CHOICES)}.",
    ),
    schedule: str = typer.Option(
        "manual",
        "--schedule",
        "-s",
        help=f"Refresh schedule. One of: {', '.join(_SCHEDULE_CHOICES)}.",
    ),
) -> None:
    """Register ``symbol`` for ``tenant`` so research-brief refresh works.

    Inserts one row in ``symbol_universe`` + one in ``watchlist_configs``.
    Both tables enforce ``(tenant_id, symbol, exchange)`` /
    ``(tenant_id, symbol_universe_id)`` uniqueness, so re-running for a
    symbol that's already registered exits non-zero.

    Usage::

        iguanatrader admin register-symbol NVDA --tenant arturo-trading

    The route ``POST /api/v1/research/briefs/{symbol}/refresh`` needs
    these rows to resolve the FK pair on the new brief; without them it
    returns HTTP 404 with the message from this command.
    """
    if tier not in _TIER_CHOICES:
        typer.echo(f"ERROR: tier must be one of {_TIER_CHOICES}, got {tier!r}.")
        raise typer.Exit(code=2)
    if methodology not in _METHODOLOGY_CHOICES:
        typer.echo(
            f"ERROR: methodology must be one of {_METHODOLOGY_CHOICES}, got {methodology!r}."
        )
        raise typer.Exit(code=2)
    if schedule not in _SCHEDULE_CHOICES:
        typer.echo(f"ERROR: schedule must be one of {_SCHEDULE_CHOICES}, got {schedule!r}.")
        raise typer.Exit(code=2)

    asyncio.run(
        _register_symbol_async(
            symbol=symbol,
            tenant_slug=tenant,
            exchange=exchange,
            tier=tier,
            methodology=methodology,
            schedule=schedule,
        )
    )


async def _register_symbol_async(
    *,
    symbol: str,
    tenant_slug: str,
    exchange: str,
    tier: str,
    methodology: str,
    schedule: str,
) -> None:
    """Async body of the ``register-symbol`` command."""
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    from iguanatrader.contexts.research.models import SymbolUniverse, WatchlistConfig
    from iguanatrader.persistence import Tenant, engine_factory, session_factory
    from iguanatrader.shared.contextvars import with_tenant_context

    engine = engine_factory(_db_url())
    try:
        sessionmaker = session_factory(engine)

        async with sessionmaker() as session:
            tenant_row = (
                (await session.execute(select(Tenant).where(Tenant.name == tenant_slug)))
                .scalars()
                .first()
            )
            if tenant_row is None:
                typer.echo(
                    f"ERROR: tenant {tenant_slug!r} not found. Run "
                    f"`iguanatrader admin bootstrap-tenant {tenant_slug} ...` first."
                )
                raise typer.Exit(code=1)
            tenant_id = tenant_row.id

        async with with_tenant_context(tenant_id), sessionmaker() as session:
            symbol_universe_id = uuid4()
            watchlist_config_id = uuid4()
            session.add(
                SymbolUniverse(
                    id=symbol_universe_id,
                    tenant_id=tenant_id,
                    symbol=symbol,
                    exchange=exchange,
                )
            )
            session.add(
                WatchlistConfig(
                    id=watchlist_config_id,
                    tenant_id=tenant_id,
                    symbol_universe_id=symbol_universe_id,
                    tier=tier,
                    methodology=methodology,
                    brief_refresh_schedule=schedule,
                )
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                typer.echo(
                    f"ERROR: symbol {symbol!r}/{exchange!r} already registered for "
                    f"tenant {tenant_slug!r}: {exc.orig}"
                )
                raise typer.Exit(code=1) from exc
    finally:
        await engine.dispose()

    typer.echo(
        f"OK — symbol={symbol} exchange={exchange} tenant={tenant_slug} "
        f"symbol_universe_id={symbol_universe_id} watchlist_config_id={watchlist_config_id}"
    )


__all__ = ["app"]
