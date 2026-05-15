"""Replay operator CLI — ``iguanatrader replay`` (slice replay-engine-decision-quality).

Subcommand:

* ``run --from YYYY-MM-DD --to YYYY-MM-DD [--tenant <slug>] [--out PATH]``
  Loads every :class:`TradeProposal` in the window, replays each
  against the canonical exit-policy matrix
  (:data:`DEFAULT_POLICIES`), and writes a one-page HTML report.

Lazy imports per gotcha #29 — typer ``--help`` stays snappy.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import typer

from iguanatrader.cli._tenant import db_url, resolve_tenant_id

app: typer.Typer = typer.Typer(
    name="replay",
    help="Decision-quality counterfactual replay (slice replay-engine-decision-quality).",
    no_args_is_help=True,
)

_DEFAULT_OUT = Path("data/replay-reports/report.html")


def _parse_iso_date(raw: str, *, flag: str) -> datetime:
    try:
        d = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise typer.BadParameter(
            f"{flag} must be ISO-8601 (e.g. 2026-01-15 or 2026-01-15T00:00:00)"
        ) from exc
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d


@app.command("run")
def run(
    from_date: str = typer.Option(
        ...,
        "--from",
        "-f",
        help="Window start (inclusive), ISO-8601 date or datetime.",
    ),
    to_date: str = typer.Option(
        ...,
        "--to",
        "-t",
        help="Window end (exclusive), ISO-8601 date or datetime.",
    ),
    tenant: str | None = typer.Option(
        None,
        "--tenant",
        help="Tenant slug; defaults to the first tenant.",
    ),
    out_path: Path = typer.Option(  # noqa: B008  # typer factory pattern, matches sibling CLIs
        _DEFAULT_OUT,
        "--out",
        "-o",
        help="Output HTML file path.",
    ),
    lookback_bars: int = typer.Option(
        400,
        "--lookback-bars",
        help="Number of historical 1d bars to pull per proposal symbol.",
    ),
) -> None:
    """Run the replay + write the HTML report."""
    asyncio.run(_run_async(from_date, to_date, tenant, out_path, lookback_bars))


async def _run_async(
    from_raw: str, to_raw: str, tenant: str | None, out_path: Path, lookback_bars: int
) -> None:
    from iguanatrader.contexts.replay.models import DEFAULT_POLICIES
    from iguanatrader.contexts.replay.report import write_report
    from iguanatrader.contexts.replay.service import ReplayService
    from iguanatrader.contexts.trading.market_data.db import DBMarketDataAdapter
    from iguanatrader.persistence import engine_factory, session_factory
    from iguanatrader.shared.contextvars import session_var, with_tenant_context

    window_start = _parse_iso_date(from_raw, flag="--from")
    window_end = _parse_iso_date(to_raw, flag="--to")
    if window_end <= window_start:
        raise typer.BadParameter("--to must be strictly after --from")

    tenant_id = await resolve_tenant_id(tenant)
    typer.echo(
        f"replay: tenant={tenant_id} window={window_start.isoformat()} → "
        f"{window_end.isoformat()} policies={len(DEFAULT_POLICIES)}"
    )

    engine = engine_factory(db_url())
    try:
        sessionmaker = session_factory(engine)
        async with sessionmaker() as session:
            session_var.set(session)
            market_data_port = DBMarketDataAdapter()
            service = ReplayService(
                session=session,
                market_data_port=market_data_port,
                lookback_bars=lookback_bars,
            )
            async with with_tenant_context(tenant_id):
                result = await service.replay_window(
                    window_start=window_start,
                    window_end=window_end,
                    policies=DEFAULT_POLICIES,
                )
    finally:
        await engine.dispose()

    written = write_report(result, out_path=out_path)
    typer.echo(
        f"replay: wrote {written}  "
        f"({len(result.rows)} proposals, "
        f"{result.proposals_skipped_no_bars} skipped no-bars)"
    )


__all__ = ["app"]
