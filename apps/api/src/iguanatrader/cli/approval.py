"""Approval operator CLI — `iguanatrader approval <subcommand>`.

Auto-discovered by slice 5's :func:`_register_subcommands`. Exports a
top-level ``app: typer.Typer`` so the loader picks it up.

Subcommands:

* ``list`` — list pending approval requests for the current tenant.
* ``audit <request_id>`` — full chain (request + decision row).
* ``sweep-expired`` — manually run the timeout sweeper. Slice O2's
  scheduler will call the same callable on a cron later.

Heavy imports (SQLAlchemy session, repository) are kept lazy inside
each subcommand body per gotcha #29 (CLI ``--help`` performance).
"""

from __future__ import annotations

import asyncio
import os

import typer

app: typer.Typer = typer.Typer(
    name="approval",
    help="Approval operator commands.",
    no_args_is_help=True,
)


_DEFAULT_DB_URL = "sqlite+aiosqlite:///./data/iguanatrader.db"


def _db_url() -> str:
    return os.getenv("IGUANA_DATABASE_URL") or _DEFAULT_DB_URL


@app.command("list")
def list_pending() -> None:
    """List pending approval requests for the current tenant."""

    async def _run() -> None:
        # Heavy imports kept lazy so `--help` is fast.
        from iguanatrader.contexts.approval.repository import (
            ApprovalRepository,
        )
        from iguanatrader.persistence import (
            engine_factory,
            session_factory,
        )
        from iguanatrader.shared.contextvars import session_var

        engine = engine_factory(_db_url())
        try:
            sessionmaker = session_factory(engine)
            async with sessionmaker() as session:
                session_var.set(session)
                repo = ApprovalRepository()
                rows = await repo.list_pending()
        finally:
            await engine.dispose()
        if not rows:
            typer.echo("No pending approval requests.")
            return
        for row in rows:
            typer.echo(
                f"{row.id}  proposal={row.proposal_id}  "
                f"channels={row.delivered_to_channels}  "
                f"expires_at={row.expires_at.isoformat()}"
            )

    asyncio.run(_run())


@app.command("audit")
def audit(request_id: str = typer.Argument(...)) -> None:
    """Show the full audit chain (request + decision) for a request id."""

    async def _run() -> None:
        from uuid import UUID

        from iguanatrader.contexts.approval.repository import (
            ApprovalRepository,
        )
        from iguanatrader.persistence import (
            engine_factory,
            session_factory,
        )
        from iguanatrader.shared.contextvars import session_var

        rid = UUID(request_id)
        engine = engine_factory(_db_url())
        try:
            sessionmaker = session_factory(engine)
            async with sessionmaker() as session:
                session_var.set(session)
                repo = ApprovalRepository()
                request = await repo.get_request(rid)
                decision = await repo.get_decision(rid)
        finally:
            await engine.dispose()
        if request is None:
            typer.echo(f"No request found for id={request_id}")
            raise typer.Exit(code=1)
        typer.echo(f"REQUEST  id={request.id}")
        typer.echo(f"  proposal_id={request.proposal_id}")
        typer.echo(f"  channels={request.delivered_to_channels}")
        typer.echo(f"  created_at={request.created_at.isoformat()}")
        typer.echo(f"  expires_at={request.expires_at.isoformat()}")
        if decision is None:
            typer.echo("DECISION  (none — pending or timeout-eligible)")
        else:
            typer.echo(f"DECISION  id={decision.id}")
            typer.echo(f"  outcome={decision.outcome}")
            typer.echo(f"  channel={decision.decided_via_channel}")
            typer.echo(f"  latency_ms={decision.latency_ms}")
            typer.echo(f"  created_at={decision.created_at.isoformat()}")

    asyncio.run(_run())


@app.command("sweep-expired")
def sweep_expired() -> None:
    """Run the timeout sweeper. Records timeout decisions for expired requests."""

    async def _run() -> None:
        from iguanatrader.contexts.approval.bootstrap import (
            get_message_bus,
            make_repository,
        )
        from iguanatrader.contexts.approval.service import ApprovalService
        from iguanatrader.persistence import (
            engine_factory,
            session_factory,
        )
        from iguanatrader.shared.contextvars import session_var

        engine = engine_factory(_db_url())
        try:
            sessionmaker = session_factory(engine)
            async with sessionmaker() as session:
                session_var.set(session)
                service = ApprovalService(
                    repository=make_repository(),
                    message_bus=get_message_bus(),
                )
                decisions = await service.sweep_expired_requests()
                await session.commit()
        finally:
            await engine.dispose()
        typer.echo(f"Recorded {len(decisions)} timeout decisions.")

    asyncio.run(_run())


__all__ = ["app"]
