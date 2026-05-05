"""Operator CLI subcommands — ``iguanatrader ops {halt,resume,override}``.

Auto-discovered by :mod:`iguanatrader.cli.main` (slice 5 dynamic
discovery loop). Module exports ``app: typer.Typer`` instance — the
loop converts the module name ``ops`` to the CLI surface
``iguanatrader ops``.

Per gotcha #29: heavy dependencies (SQLAlchemy session factory,
async event loop) are imported lazily *inside* command bodies — the
top of this module imports only :mod:`typer` + project modules that
have no transitive heavy imports. ``iguanatrader --version``, which
auto-discovers every CLI submodule, must remain fast.

structlog event-name convention (per K1 prompt):
``risk.kill_switch.activated`` / ``risk.kill_switch.deactivated`` /
``risk.override.recorded`` for the three commands.

Reason validation: every command's ``--reason`` argument requires
≥20 characters per FR25 / NFR-S5; Typer-level validation rejects
shorter values BEFORE reaching the service so the CLI surface fails
fast with a clear UX message.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any
from uuid import UUID

import typer

app: typer.Typer = typer.Typer(
    name="ops",
    help="Operator commands — kill-switch, overrides, audit.",
    no_args_is_help=True,
    add_completion=False,
)

#: Reason floor mirrors :data:`RiskService._REASON_MIN_LENGTH`.
_REASON_MIN_LENGTH: int = 20

#: Default tenant id env var. Operators set this on the CLI host so
#: ``iguanatrader ops halt --reason "..."`` knows which tenant to act
#: on without a positional arg. Forward-compat: a future flag
#: ``--tenant-id`` overrides this for multi-tenant operators.
_TENANT_ID_ENV: str = "IGUANATRADER_OPS_TENANT_ID"

#: Default actor user id env var (for the audit trail).
_ACTOR_USER_ID_ENV: str = "IGUANATRADER_OPS_ACTOR_USER_ID"


def _validate_reason(value: str) -> str:
    """Typer validator: reject reasons shorter than 20 chars."""
    if value is None:
        raise typer.BadParameter("--reason is required")
    if len(value.strip()) < _REASON_MIN_LENGTH:
        raise typer.BadParameter(
            f"--reason must be at least {_REASON_MIN_LENGTH} characters "
            f"(got {len(value.strip())})."
        )
    return value


def _resolve_tenant_id(tenant_id: str | None) -> UUID:
    """Resolve the tenant id from CLI flag or env var; raise on neither."""
    raw = tenant_id or os.getenv(_TENANT_ID_ENV)
    if not raw:
        raise typer.BadParameter(
            f"--tenant-id is required (or set {_TENANT_ID_ENV} env var)."
        )
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise typer.BadParameter(f"--tenant-id is not a valid UUID: {raw!r}") from exc


def _resolve_actor_user_id(actor: str | None) -> UUID | None:
    """Resolve the actor user id from CLI flag or env var. None if neither."""
    raw = actor or os.getenv(_ACTOR_USER_ID_ENV)
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise typer.BadParameter(f"--actor-user-id is not a valid UUID: {raw!r}") from exc


async def _run_with_session(coro_factory: Any) -> Any:
    """Open a request-scoped session, await the supplied coroutine factory.

    Lazy imports per gotcha #29: SQLAlchemy + persistence machinery
    only load when an op command actually runs.
    """
    # Lazy import — keeps `iguanatrader --version` fast.
    from iguanatrader.api.deps import _get_session_factory

    sessionmaker = _get_session_factory()
    async with sessionmaker() as session:
        result = await coro_factory(session)
        await session.commit()
        return result


@app.command("halt")
def halt(
    reason: str = typer.Option(..., "--reason", help="≥20 char operator reason."),
    tenant_id: str | None = typer.Option(
        None, "--tenant-id", help="Tenant UUID (or env IGUANATRADER_OPS_TENANT_ID)."
    ),
    actor_user_id: str | None = typer.Option(
        None, "--actor-user-id", help="Actor user UUID (or env IGUANATRADER_OPS_ACTOR_USER_ID)."
    ),
) -> None:
    """Activate the kill-switch via ``source='cli'``."""
    reason_clean = _validate_reason(reason)
    tenant_uuid = _resolve_tenant_id(tenant_id)
    actor_uuid = _resolve_actor_user_id(actor_user_id)

    # Lazy imports — see gotcha #29.
    from iguanatrader.contexts.risk.repository import RiskRepository
    from iguanatrader.contexts.risk.service import RiskService
    from iguanatrader.shared.contextvars import with_tenant_context

    async def _do(session: Any) -> UUID:
        async with with_tenant_context(tenant_uuid):
            service = RiskService(repository=RiskRepository(session))
            return await service.activate_kill_switch(
                tenant_id=tenant_uuid,
                source="cli",
                actor_user_id=actor_uuid,
                reason=reason_clean,
            )

    event_id = asyncio.run(_run_with_session(_do))
    typer.echo(f"kill-switch activated: event_id={event_id}")


@app.command("resume")
def resume(
    reason: str = typer.Option(..., "--reason", help="≥20 char operator reason."),
    tenant_id: str | None = typer.Option(None, "--tenant-id"),
    actor_user_id: str | None = typer.Option(None, "--actor-user-id"),
) -> None:
    """Deactivate the kill-switch via ``source='cli'``."""
    reason_clean = _validate_reason(reason)
    tenant_uuid = _resolve_tenant_id(tenant_id)
    actor_uuid = _resolve_actor_user_id(actor_user_id)

    from iguanatrader.contexts.risk.repository import RiskRepository
    from iguanatrader.contexts.risk.service import RiskService
    from iguanatrader.shared.contextvars import with_tenant_context

    async def _do(session: Any) -> UUID:
        async with with_tenant_context(tenant_uuid):
            service = RiskService(repository=RiskRepository(session))
            return await service.deactivate_kill_switch(
                tenant_id=tenant_uuid,
                source="cli",
                actor_user_id=actor_uuid,
                reason=reason_clean,
            )

    event_id = asyncio.run(_run_with_session(_do))
    typer.echo(f"kill-switch deactivated: event_id={event_id}")


@app.command("override")
def override(
    proposal_id: str = typer.Option(..., "--proposal-id", help="Proposal UUID."),
    risk_evaluation_id: str = typer.Option(..., "--risk-evaluation-id"),
    reason: str = typer.Option(..., "--reason", help="≥20 char operator reason."),
    tenant_id: str | None = typer.Option(None, "--tenant-id"),
    actor_user_id: str | None = typer.Option(None, "--actor-user-id"),
) -> None:
    """Record an override audit row.

    The ``confirmation_chain`` is synthesised here (single-actor CLI
    confirmation) — ``first`` and ``second`` confirmations both
    reference the actor + the ``"cli"`` channel + the same timestamp.
    Production override flow uses the dashboard / channel commands;
    this CLI is the operator escape hatch (per design D5 + slice
    K1's CLI ops contract).
    """
    reason_clean = _validate_reason(reason)
    tenant_uuid = _resolve_tenant_id(tenant_id)
    actor_uuid = _resolve_actor_user_id(actor_user_id)
    if actor_uuid is None:
        raise typer.BadParameter(
            "--actor-user-id is required for override (or set "
            "IGUANATRADER_OPS_ACTOR_USER_ID)."
        )
    try:
        proposal_uuid = uuid.UUID(proposal_id)
        risk_eval_uuid = uuid.UUID(risk_evaluation_id)
    except ValueError as exc:
        raise typer.BadParameter(f"invalid UUID: {exc}") from exc

    from iguanatrader.contexts.risk.models import (
        Confirmation,
        ConfirmationChain,
    )
    from iguanatrader.contexts.risk.repository import RiskRepository
    from iguanatrader.contexts.risk.service import RiskService
    from iguanatrader.shared.contextvars import with_tenant_context
    from iguanatrader.shared.time import now as utc_now

    async def _do(session: Any) -> UUID:
        async with with_tenant_context(tenant_uuid):
            now = utc_now()
            chain = ConfirmationChain(
                first_confirmation=Confirmation(
                    channel="cli", at=now, actor_user_id=actor_uuid
                ),
                second_confirmation=Confirmation(
                    channel="cli", at=now, actor_user_id=actor_uuid
                ),
            )
            service = RiskService(repository=RiskRepository(session))
            return await service.record_override(
                tenant_id=tenant_uuid,
                proposal_id=proposal_uuid,
                risk_evaluation_id=risk_eval_uuid,
                authorised_by_user_id=actor_uuid,
                reason_text=reason_clean,
                confirmation_chain=chain,
                state_snapshot_at_override={},
            )

    override_id = asyncio.run(_run_with_session(_do))
    typer.echo(f"override recorded: id={override_id}")


__all__ = ["app"]
