"""Settings CLI - ``iguanatrader settings <subcommand>`` (slice R6).

Two subcommands under ``feature-flag``:

* ``feature-flag get [--tenant=<slug>]`` - prints current flags.
* ``feature-flag set <KEY>=<VALUE> [--tenant=<slug>]`` - updates one
  whitelisted flag (currently only ``hindsight_recall_enabled``).

Heavy imports kept lazy per gotcha #29.
"""

from __future__ import annotations

import asyncio
import json

import typer

from iguanatrader.cli._tenant import db_url, resolve_tenant_id

app: typer.Typer = typer.Typer(
    name="settings",
    help="Tenant settings (slice R6 hindsight-integration).",
    no_args_is_help=True,
)


feature_flag_app: typer.Typer = typer.Typer(
    name="feature-flag",
    help="Read + write tenant.feature_flags.",
    no_args_is_help=True,
)
app.add_typer(feature_flag_app, name="feature-flag")


_KNOWN_FLAGS: tuple[str, ...] = ("hindsight_recall_enabled",)


@feature_flag_app.command("get")
def feature_flag_get(
    tenant: str | None = typer.Option(None, "--tenant", help="Tenant slug."),
) -> None:
    """Print the current tenant's feature_flags as JSON."""
    asyncio.run(_run_get(tenant=tenant))


@feature_flag_app.command("set")
def feature_flag_set(
    assignment: str = typer.Argument(
        ...,
        help='KEY=VALUE (e.g. "hindsight_recall_enabled=true").',
    ),
    tenant: str | None = typer.Option(None, "--tenant", help="Tenant slug."),
) -> None:
    """Update one whitelisted feature flag for the current tenant."""
    if "=" not in assignment:
        typer.echo(
            f"Invalid assignment {assignment!r}; expected KEY=VALUE.",
            err=True,
        )
        raise typer.Exit(code=2)
    key, raw_value = assignment.split("=", 1)
    key = key.strip()
    value_str = raw_value.strip().lower()
    if key not in _KNOWN_FLAGS:
        typer.echo(
            f"Unknown flag {key!r}; whitelisted: {list(_KNOWN_FLAGS)}.",
            err=True,
        )
        raise typer.Exit(code=2)
    if value_str in {"true", "1", "yes", "on"}:
        value: bool = True
    elif value_str in {"false", "0", "no", "off"}:
        value = False
    else:
        typer.echo(
            f"Invalid bool value {raw_value!r}; expected true/false.",
            err=True,
        )
        raise typer.Exit(code=2)
    asyncio.run(_run_set(tenant=tenant, key=key, value=value))


async def _run_get(*, tenant: str | None) -> None:
    from iguanatrader.persistence import (
        Tenant,
        engine_factory,
        session_factory,
    )

    tenant_id = await resolve_tenant_id(tenant)
    engine = engine_factory(db_url())
    sm = session_factory(engine)
    try:
        async with sm() as session:
            row = await session.get(Tenant, tenant_id)
            if row is None:
                typer.echo(f"Tenant {tenant_id} not found.", err=True)
                raise typer.Exit(code=2)
            flags = dict(row.feature_flags or {})
            typer.echo(json.dumps(flags, indent=2, sort_keys=True))
    finally:
        await engine.dispose()


async def _run_set(*, tenant: str | None, key: str, value: bool) -> None:
    from iguanatrader.persistence import (
        Tenant,
        engine_factory,
        session_factory,
    )

    tenant_id = await resolve_tenant_id(tenant)
    engine = engine_factory(db_url())
    sm = session_factory(engine)
    try:
        async with sm() as session:
            row = await session.get(Tenant, tenant_id)
            if row is None:
                typer.echo(f"Tenant {tenant_id} not found.", err=True)
                raise typer.Exit(code=2)
            current = dict(row.feature_flags or {})
            current[key] = value
            row.feature_flags = current
            await session.commit()
            typer.echo(f"Set {key}={value} for tenant {tenant_id}.")
    finally:
        await engine.dispose()


__all__ = ["app"]
