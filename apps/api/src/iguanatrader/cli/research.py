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
* ``ingest sec-edgar <symbol>`` (Ingestion Wave I0) — fetch + persist
  SEC EDGAR filings and XBRL companyfacts as ``research_facts`` rows so
  the tier-A feature provider can serve real values to brief synthesis.
* ``ingest fred --series <csv> [--backfill Ny]`` (Ingestion Wave I1) —
  fetch + persist macro time-series from FRED. Backfill flag seeds deep
  history (e.g. ``--backfill 5y``) so methodology features that depend
  on regime / mean-reversion windows have data.
* ``ingest openbb <symbol>`` (Ingestion Wave I2) — fetch fundamentals
  + analyst ratings + ESG via the OpenBB sidecar (loopback HTTP, AGPL-
  isolated per ADR-015). Default provider is YFinance (free, no key).

Heavy imports kept lazy per gotcha #29 (``--help`` performance).
"""

from __future__ import annotations

import asyncio
import os
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

import typer

# Slice T4 §1.1: tenant resolution + db_url extracted to cli/_tenant.py so
# `cli/trading.py` (and future CLI subcommands) can share the helper.
from iguanatrader.cli._tenant import db_url as _db_url
from iguanatrader.cli._tenant import resolve_tenant_id as _resolve_tenant_id

app: typer.Typer = typer.Typer(
    name="research",
    help="Research operator commands (slice R5).",
    no_args_is_help=True,
)

# Subcommand group for ingestion CLIs (Ingestion Wave I0+). Each source
# adapter gets a sibling command under ``iguanatrader research ingest``.
ingest_app: typer.Typer = typer.Typer(
    name="ingest",
    help="Fetch + persist research facts from external sources.",
    no_args_is_help=True,
)
app.add_typer(ingest_app, name="ingest")


_VALID_METHODOLOGIES = (
    "three_pillar",
    "canslim",
    "magic_formula",
    "qarp",
    "multi_factor",
)


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


# ----------------------------------------------------------------------
# Ingestion Wave (I0+) — research_facts pipeline activators
# ----------------------------------------------------------------------


@ingest_app.command("sec-edgar")
def ingest_sec_edgar(
    symbol: str = typer.Argument(
        ...,
        help="Ticker symbol to ingest (e.g. NVDA).",
    ),
    since: str | None = typer.Option(
        None,
        "--since",
        help=(
            "ISO 8601 date (YYYY-MM-DD) — only emit drafts newer than this. "
            "Default: full history (every filing + every XBRL fact)."
        ),
    ),
    tenant: str | None = typer.Option(
        None,
        "--tenant",
        help="Tenant slug; defaults to the first tenant when single-tenant.",
    ),
) -> None:
    """Pull SEC EDGAR filings + XBRL companyfacts into ``research_facts``.

    Requires ``SEC_EDGAR_USER_AGENT="<company> <email>"`` per SEC Fair
    Access policy. The symbol must already exist in ``symbol_universe``
    for the tenant (use ``iguanatrader admin register-symbol`` first).

    Idempotent on ``(tenant_id, dedupe_key)`` — the adapter stamps a
    deterministic ``dedupe_key`` per draft (accession number for filings,
    ``cik:concept:end_date:form`` for XBRL facts), so re-running the
    command never duplicates rows.

    Usage::

        iguanatrader research ingest sec-edgar NVDA
        iguanatrader research ingest sec-edgar NVDA --since 2024-01-01
    """
    since_dt: datetime | None = None
    if since is not None:
        try:
            since_dt = datetime.fromisoformat(since).replace(tzinfo=UTC)
        except ValueError as exc:
            typer.echo(f"ERROR: --since must be ISO 8601 date (YYYY-MM-DD); got {since!r}: {exc}")
            raise typer.Exit(code=2) from exc

    import structlog

    log = structlog.get_logger("iguanatrader.cli.research.ingest")
    log.info("cli.research.ingest.sec_edgar.invoked", symbol=symbol, since=since)

    asyncio.run(_ingest_sec_edgar_async(symbol=symbol, since=since_dt, tenant_slug=tenant))


async def _ingest_sec_edgar_async(
    *,
    symbol: str,
    since: datetime | None,
    tenant_slug: str | None,
) -> None:
    """Async body of the ``ingest sec-edgar`` command."""
    from dataclasses import replace as dc_replace

    import sqlalchemy as sa

    from iguanatrader.contexts.research.models import SymbolUniverse
    from iguanatrader.contexts.research.repository import ResearchRepository
    from iguanatrader.contexts.research.sources.sec_edgar import SECEdgarSource
    from iguanatrader.persistence import engine_factory, session_factory
    from iguanatrader.shared.contextvars import session_var, tenant_id_var

    tenant_id = await _resolve_tenant_id(tenant_slug)
    engine = engine_factory(_db_url())
    try:
        sessionmaker = session_factory(engine)
        async with sessionmaker() as session:
            tenant_id_var.set(tenant_id)
            session_var.set(session)

            sym_row = (
                await session.execute(
                    sa.select(SymbolUniverse.id).where(SymbolUniverse.symbol == symbol)
                )
            ).first()
            if sym_row is None:
                typer.echo(
                    f"ERROR: symbol {symbol!r} not registered for this tenant. Run "
                    f"`iguanatrader admin register-symbol {symbol} --tenant <slug>` first."
                )
                raise typer.Exit(code=1)
            symbol_universe_id = sym_row[0]

            adapter = SECEdgarSource()
            repo = ResearchRepository()

            inserted = 0
            for draft in adapter.fetch(symbol, since):
                stamped = dc_replace(draft, symbol_universe_id=symbol_universe_id)
                await repo.insert_fact(stamped)
                inserted += 1

            await session.commit()
    finally:
        await engine.dispose()

    typer.echo(
        f"OK — symbol={symbol} since={since.isoformat() if since else 'all'} "
        f"facts_inserted={inserted}"
    )


_BACKFILL_RE = re.compile(r"^(\d+)([dmy])$")


def _parse_backfill_to_since(backfill: str) -> datetime:
    """Translate ``--backfill 5y`` / ``30d`` / ``6m`` to an absolute datetime.

    Months are approximated as 30 days; years as 365. The adapter's
    ``realtime_start`` filter is date-only so day-level granularity is
    sufficient — sub-day rounding would have no effect on the query.
    """
    match = _BACKFILL_RE.match(backfill.strip())
    if match is None:
        raise ValueError(f"--backfill must match <N>d/m/y (e.g. '5y', '30d'); got {backfill!r}")
    n = int(match.group(1))
    unit = match.group(2)
    days_per_unit = {"d": 1, "m": 30, "y": 365}[unit]
    now = datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=n * days_per_unit
    )


@ingest_app.command("fred")
def ingest_fred(
    series: str = typer.Option(
        ...,
        "--series",
        "-s",
        help=(
            "Comma-separated FRED series IDs (e.g. CPIAUCSL,UNRATE,DFF). "
            "Common picks: CPIAUCSL=CPI, UNRATE=unemployment, DFF=fed funds, "
            "GDP, M2SL, DGS10=10y-treasury."
        ),
    ),
    backfill: str | None = typer.Option(
        None,
        "--backfill",
        "-b",
        help=(
            "Backfill window: <N>d/m/y (e.g. '5y'). Default: no backfill "
            "(adapter's 1900-01-01 floor applies on first run; idempotent "
            "dedupe_key skips already-persisted vintages)."
        ),
    ),
    since: str | None = typer.Option(
        None,
        "--since",
        help=(
            "Explicit ISO 8601 date (YYYY-MM-DD). Mutually exclusive with "
            "--backfill; --since wins if both supplied."
        ),
    ),
    tenant: str | None = typer.Option(
        None,
        "--tenant",
        help="Tenant slug; defaults to the first tenant when single-tenant.",
    ),
) -> None:
    """Pull FRED macro time-series into ``research_facts``.

    Macro facts are not symbol-scoped — ``symbol_universe_id`` stays NULL
    on the row (the column is nullable per the bitemporal model).
    ALFRED-aware: revisions land as NEW facts (bitemporal
    ``recorded_from``), not overwriting prior vintages.

    Idempotent: re-running ingests only new vintages (dedupe_key is
    ``fred:<series>:<date>:<realtime_start>``).

    Usage::

        iguanatrader research ingest fred --series CPIAUCSL,UNRATE,DFF
        iguanatrader research ingest fred --series CPIAUCSL --backfill 5y
        iguanatrader research ingest fred --series GDP --since 2024-01-01
    """
    since_dt: datetime | None = None
    if since is not None:
        try:
            since_dt = datetime.fromisoformat(since).replace(tzinfo=UTC)
        except ValueError as exc:
            typer.echo(f"ERROR: --since must be ISO 8601 date (YYYY-MM-DD); got {since!r}: {exc}")
            raise typer.Exit(code=2) from exc
    elif backfill is not None:
        try:
            since_dt = _parse_backfill_to_since(backfill)
        except ValueError as exc:
            typer.echo(f"ERROR: {exc}")
            raise typer.Exit(code=2) from exc

    series_ids = [s.strip() for s in series.split(",") if s.strip()]
    if not series_ids:
        typer.echo("ERROR: --series must contain at least one non-empty FRED series id")
        raise typer.Exit(code=2)

    import structlog

    log = structlog.get_logger("iguanatrader.cli.research.ingest")
    log.info(
        "cli.research.ingest.fred.invoked",
        series=series_ids,
        backfill=backfill,
        since=since,
    )

    asyncio.run(_ingest_fred_async(series_ids=series_ids, since=since_dt, tenant_slug=tenant))


async def _ingest_fred_async(
    *,
    series_ids: list[str],
    since: datetime | None,
    tenant_slug: str | None,
) -> None:
    """Async body of the ``ingest fred`` command."""
    from iguanatrader.contexts.research.repository import ResearchRepository
    from iguanatrader.contexts.research.sources.fred import FREDSource
    from iguanatrader.persistence import engine_factory, session_factory
    from iguanatrader.shared.contextvars import session_var, tenant_id_var

    tenant_id = await _resolve_tenant_id(tenant_slug)
    engine = engine_factory(_db_url())
    try:
        sessionmaker = session_factory(engine)
        async with sessionmaker() as session:
            tenant_id_var.set(tenant_id)
            session_var.set(session)

            adapter = FREDSource()
            repo = ResearchRepository()

            per_series: dict[str, int] = {}
            for series_id in series_ids:
                count = 0
                for draft in adapter.fetch_series(series_id, since):
                    await repo.insert_fact(draft)
                    count += 1
                per_series[series_id] = count

            await session.commit()
    finally:
        await engine.dispose()

    total = sum(per_series.values())
    typer.echo(
        f"OK — series={','.join(series_ids)} "
        f"since={since.isoformat() if since else 'all'} "
        f"facts_inserted={total} ({per_series})"
    )


@ingest_app.command("openbb")
def ingest_openbb(
    symbol: str = typer.Argument(
        ...,
        help="Ticker symbol to fetch via the OpenBB sidecar (e.g. NVDA).",
    ),
    tenant: str | None = typer.Option(
        None,
        "--tenant",
        help="Tenant slug; defaults to the first tenant when single-tenant.",
    ),
) -> None:
    """Pull fundamentals + ratings + ESG from the OpenBB sidecar.

    Calls the loopback-only sidecar at ``OPENBB_SIDECAR_URL`` (default
    ``http://openbb_sidecar:8765`` inside the compose network). Yields
    up to 3 drafts per symbol — one per endpoint surface (fundamentals,
    analyst ratings, ESG score). 4xx responses skip that endpoint with
    a warning rather than failing the whole run.

    Default provider is YFinance (free, no key). Operators upgrade by
    setting OpenBB-recognized env vars on the sidecar container
    (``OPENBB_FMP_API_KEY`` / ``OPENBB_POLYGON_API_KEY`` / etc.) — see
    docs/roadmap-ingestion.md for the spend-decision principle.

    Usage::

        iguanatrader research ingest openbb NVDA
    """
    import structlog

    log = structlog.get_logger("iguanatrader.cli.research.ingest")
    log.info("cli.research.ingest.openbb.invoked", symbol=symbol)

    asyncio.run(_ingest_openbb_async(symbol=symbol, tenant_slug=tenant))


async def _ingest_openbb_async(
    *,
    symbol: str,
    tenant_slug: str | None,
) -> None:
    """Async body of the ``ingest openbb`` command."""
    from dataclasses import replace as dc_replace

    import sqlalchemy as sa

    from iguanatrader.contexts.research.models import SymbolUniverse
    from iguanatrader.contexts.research.repository import ResearchRepository
    from iguanatrader.contexts.research.sources.openbb_sidecar import OpenBBSidecarSource
    from iguanatrader.persistence import engine_factory, session_factory
    from iguanatrader.shared.contextvars import session_var, tenant_id_var

    tenant_id = await _resolve_tenant_id(tenant_slug)
    engine = engine_factory(_db_url())
    try:
        sessionmaker = session_factory(engine)
        async with sessionmaker() as session:
            tenant_id_var.set(tenant_id)
            session_var.set(session)

            sym_row = (
                await session.execute(
                    sa.select(SymbolUniverse.id).where(SymbolUniverse.symbol == symbol)
                )
            ).first()
            if sym_row is None:
                typer.echo(
                    f"ERROR: symbol {symbol!r} not registered for this tenant. Run "
                    f"`iguanatrader admin register-symbol {symbol} --tenant <slug>` first."
                )
                raise typer.Exit(code=1)
            symbol_universe_id = sym_row[0]

            adapter = OpenBBSidecarSource()
            repo = ResearchRepository()

            inserted = 0
            try:
                for draft in adapter.fetch(symbol, None):
                    stamped = dc_replace(draft, symbol_universe_id=symbol_universe_id)
                    await repo.insert_fact(stamped)
                    inserted += 1
            finally:
                adapter.close()

            await session.commit()
    finally:
        await engine.dispose()

    typer.echo(f"OK — symbol={symbol} facts_inserted={inserted}")


__all__ = ["app"]
