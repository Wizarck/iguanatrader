"""Research operator CLI — ``iguanatrader research <subcommand>`` (slice R5).

Auto-discovered by slice 5's :func:`_register_subcommands`. Exports a
top-level ``app: typer.Typer`` so the loader picks it up.

Subcommands:

* ``refresh-brief <symbol> [--methodology <name>] [--tenant <slug>]`` —
  synchronously synthesise a fresh brief for ``symbol``. Prints the
  brief id + version + first 200 chars of body_markdown.
* ``audit <brief_id> [--tenant <slug>]`` — render the audit-trail rows
  for ``brief_id`` as markdown (mirrors j3.md §3 Step 3 "Copy as
  markdown" frontend action shape).

Heavy imports kept lazy per gotcha #29 (``--help`` performance).
"""

from __future__ import annotations

import asyncio
import os
from uuid import UUID

import typer

app: typer.Typer = typer.Typer(
    name="research",
    help="Research operator commands (slice R5).",
    no_args_is_help=True,
)


_DEFAULT_DB_URL = "sqlite+aiosqlite:///./data/iguanatrader.db"
_VALID_METHODOLOGIES = (
    "three_pillar",
    "canslim",
    "magic_formula",
    "qarp",
    "multi_factor",
)


def _db_url() -> str:
    return os.getenv("IGUANA_DATABASE_URL") or _DEFAULT_DB_URL


async def _resolve_tenant_id(tenant: str | None) -> UUID:
    """Resolve a tenant name → UUID; default to first tenant if None.

    Replicates the admin-CLI tenant-resolution pattern. Single-tenant
    deployments need no flag.
    """
    from sqlalchemy import select

    from iguanatrader.persistence import Tenant, engine_factory, session_factory

    engine = engine_factory(_db_url())
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


@app.command("refresh-brief")
def refresh_brief(
    symbol: str = typer.Argument(..., help="Ticker symbol to synthesise (e.g. AAPL)."),
    methodology: str = typer.Option(
        "three_pillar",
        "--methodology",
        "-m",
        help=f"One of: {', '.join(_VALID_METHODOLOGIES)}.",
    ),
    tenant: str | None = typer.Option(
        None,
        "--tenant",
        help="Tenant slug; defaults to the first tenant if single-tenant.",
    ),
) -> None:
    """Synthesise a fresh brief for ``symbol`` using ``methodology``."""

    if methodology not in _VALID_METHODOLOGIES:
        typer.echo(f"Invalid methodology {methodology!r}; expected one of {_VALID_METHODOLOGIES}")
        raise typer.Exit(code=2)

    import structlog

    log = structlog.get_logger("iguanatrader.cli.research")
    log.info("cli.research.refresh.invoked", symbol=symbol, methodology=methodology)

    async def _run() -> None:
        from iguanatrader.contexts.research.feature_provider import (
            CompositeFeatureProvider,
            TierAFeatureProvider,
            TierBFeatureProvider,
            TierCFeatureProvider,
        )
        from iguanatrader.contexts.research.repository import ResearchRepository
        from iguanatrader.contexts.research.service import BriefService
        from iguanatrader.contexts.research.synthesis import (
            AuditTrailService,
            FakeLLMClient,
            Synthesizer,
        )
        from iguanatrader.contexts.research.synthesis.llm_client import LLMClient
        from iguanatrader.persistence import engine_factory, session_factory
        from iguanatrader.shared.contextvars import session_var, tenant_id_var

        tenant_id = await _resolve_tenant_id(tenant)
        engine = engine_factory(_db_url())
        try:
            sessionmaker = session_factory(engine)
            async with sessionmaker() as session:
                tenant_id_var.set(tenant_id)
                session_var.set(session)
                repo = ResearchRepository()
                composite = CompositeFeatureProvider(
                    tier_a=TierAFeatureProvider(repo),
                    tier_b=TierBFeatureProvider(repo),
                    tier_c=TierCFeatureProvider(repo),
                )
                # Slice deployment-foundation §3.A.2 — env-gated production
                # adapter swap. Production envs with ANTHROPIC_API_KEY set
                # use AnthropicLLMClient; dev/test default to FakeLLMClient.
                env = (os.environ.get("IGUANATRADER_ENV") or "").strip().lower()
                llm_client: LLMClient
                if env in {"paper", "live", "production"} and os.environ.get("ANTHROPIC_API_KEY"):
                    from iguanatrader.contexts.research.synthesis.anthropic_client import (
                        build_anthropic_llm_client_from_env,
                    )

                    llm_client = build_anthropic_llm_client_from_env()
                else:
                    llm_client = FakeLLMClient()
                service = BriefService(
                    repository=repo,
                    composite_provider=composite,
                    synthesizer=Synthesizer(llm_client=llm_client),
                    audit_service=AuditTrailService(repo),
                )
                outcome = await service.refresh(symbol=symbol, methodology=methodology)
                await session.commit()
        finally:
            await engine.dispose()

        brief = outcome.brief
        typer.echo(f"BRIEF  id={brief.id}")
        typer.echo(f"  symbol_universe_id={brief.symbol_universe_id}")
        typer.echo(f"  version={brief.version}")
        typer.echo(f"  methodology={brief.methodology}")
        typer.echo(f"  partial={brief.partial}")
        excerpt = brief.thesis_text[:200].replace("\n", " ")
        typer.echo(f"  body[:200]={excerpt}…")

    asyncio.run(_run())


@app.command("audit")
def audit(
    brief_id: str = typer.Argument(..., help="UUID of the brief to render."),
    tenant: str | None = typer.Option(None, "--tenant"),
) -> None:
    """Render audit-trail rows for ``brief_id`` as markdown."""

    import structlog

    log = structlog.get_logger("iguanatrader.cli.research")
    log.info("cli.research.audit.invoked", brief_id=brief_id)

    try:
        bid = UUID(brief_id)
    except ValueError:
        typer.echo(f"Invalid UUID: {brief_id!r}")
        raise typer.Exit(code=2) from None

    async def _run() -> None:
        from iguanatrader.contexts.research.repository import ResearchRepository
        from iguanatrader.persistence import engine_factory, session_factory
        from iguanatrader.shared.contextvars import session_var, tenant_id_var

        tenant_id = await _resolve_tenant_id(tenant)
        engine = engine_factory(_db_url())
        try:
            sessionmaker = session_factory(engine)
            async with sessionmaker() as session:
                tenant_id_var.set(tenant_id)
                session_var.set(session)
                repo = ResearchRepository()
                rows = await repo.audit_trail_for_brief(bid)
        finally:
            await engine.dispose()
        if not rows:
            typer.echo(f"No audit trail rows for brief_id={brief_id}")
            return
        typer.echo(f"# Audit trail — brief_id={brief_id}\n")
        for row in rows:
            typer.echo(f"## {row.metric}")
            typer.echo(f"- formula: `{row.formula}`")
            typer.echo(f"- inputs: {row.inputs}")
            typer.echo(f"- final_output: {row.final_output}")
            typer.echo("")

    asyncio.run(_run())


__all__ = ["app"]
