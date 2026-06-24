"""Market-data ingestion CLI — ``iguanatrader market-data <subcommand>``.

Slice T4-followup-market-data §2.12. Two subcommands:

* ``sync [--symbols=AAPL,MSFT] [--timeframe=1d] [--lookback-bars=200]``
  — invoke the ingestion service for the watchlist (or a CSV).
* ``backfill --symbol=AAPL [--days=365] [--timeframe=1d]`` — long-window
  backfill for a single symbol (computes ``lookback_bars`` from
  ``days * bars_per_day``).

Both subcommands respect the audit-table-backed rate limit
(``IGUANATRADER_MARKET_DATA_MAX_INVOCATIONS_PER_HOUR``) and exit with
code 2 when the budget is exhausted.

Heavy imports kept lazy per gotcha #29 (``--help`` performance).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from typing import TYPE_CHECKING

import typer

from iguanatrader.cli._tenant import db_url, resolve_tenant_id

if TYPE_CHECKING:
    pass


app: typer.Typer = typer.Typer(
    name="market-data",
    help="Market-data ingestion (slice T4-followup-market-data).",
    no_args_is_help=True,
)


_BARS_PER_DAY: dict[str, int] = {
    "1d": 1,
    "1h": 24,
    "1m": 1440,
}


def _parse_csv(raw: str | None, default: list[str]) -> list[str]:
    if raw is None or not raw.strip():
        return default
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


@app.command("sync")
def sync(
    symbols: str | None = typer.Option(
        None,
        "--symbols",
        help="CSV symbol list. Defaults to IGUANATRADER_DEFAULT_WATCHLIST_SYMBOLS.",
    ),
    timeframe: str = typer.Option("1d", "--timeframe", help="Bar timeframe."),
    lookback_bars: int = typer.Option(200, "--lookback-bars"),
    tenant: str | None = typer.Option(None, "--tenant"),
) -> None:
    """Ingest historical bars for the configured watchlist (rate-limited)."""
    asyncio.run(
        _run_sync(
            symbols_csv=symbols,
            timeframe=timeframe,
            lookback_bars=lookback_bars,
            tenant=tenant,
            invoked_by="cli-sync",
        )
    )


@app.command("replay")
def replay(
    routine: str = typer.Option(
        ...,
        "--routine",
        help="One of: premarket, midday, postmarket, weekly_review.",
    ),
    date: str = typer.Option(
        ...,
        "--date",
        help="ISO 8601 date YYYY-MM-DD (the as_of point for bars).",
    ),
    symbols: str | None = typer.Option(
        None,
        "--symbols",
        help="CSV symbol list. Defaults to IGUANATRADER_DEFAULT_WATCHLIST_SYMBOLS.",
    ),
    timeframe: str = typer.Option("1d", "--timeframe"),
    lookback_bars: int = typer.Option(200, "--lookback-bars"),
    tenant: str | None = typer.Option(None, "--tenant"),
) -> None:
    """Re-evaluate strategies against historical bars (slice market-data-replay)."""
    asyncio.run(
        _run_replay(
            routine=routine,
            date=date,
            symbols_csv=symbols,
            timeframe=timeframe,
            lookback_bars=lookback_bars,
            tenant=tenant,
        )
    )


@app.command("backfill")
def backfill(
    symbol: str = typer.Option(..., "--symbol", help="Single symbol to backfill."),
    days: int = typer.Option(365, "--days", help="Calendar-day lookback."),
    timeframe: str = typer.Option("1d", "--timeframe"),
    tenant: str | None = typer.Option(None, "--tenant"),
) -> None:
    """Long-window backfill for a single symbol (rate-limited)."""
    bars_per_day = _BARS_PER_DAY.get(timeframe, 1)
    lookback_bars = max(1, days * bars_per_day)
    asyncio.run(
        _run_sync(
            symbols_csv=symbol,
            timeframe=timeframe,
            lookback_bars=lookback_bars,
            tenant=tenant,
            invoked_by="cli-backfill",
        )
    )


async def _run_replay(
    *,
    routine: str,
    date: str,
    symbols_csv: str | None,
    timeframe: str,
    lookback_bars: int,
    tenant: str | None,
) -> None:
    """Construct replay service + invoke; print table to stdout."""
    from datetime import UTC, datetime

    from iguanatrader.contexts.trading.market_data.db import DBMarketDataAdapter
    from iguanatrader.contexts.trading.market_data.replay import (
        MarketDataReplayService,
    )
    from iguanatrader.contexts.trading.repository import StrategyConfigRepository
    from iguanatrader.persistence import engine_factory, session_factory
    from iguanatrader.shared.contextvars import session_var, tenant_id_var

    try:
        as_of = datetime.fromisoformat(date).replace(tzinfo=UTC)
    except ValueError as exc:
        typer.echo(f"Invalid --date={date!r}; expected YYYY-MM-DD: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    default_watchlist = _parse_csv(
        os.environ.get("IGUANATRADER_DEFAULT_WATCHLIST_SYMBOLS"),
        default=["AAPL", "MSFT", "GOOGL"],
    )
    symbols = _parse_csv(symbols_csv, default=default_watchlist)
    if not symbols:
        typer.echo("No symbols supplied (CSV empty + no default watchlist).", err=True)
        raise typer.Exit(code=2)

    tenant_id = await resolve_tenant_id(tenant)
    engine = engine_factory(db_url())
    sm = session_factory(engine)

    try:
        async with sm() as session:
            tenant_id_var.set(tenant_id)
            session_var.set(session)
            from iguanatrader.cli.trading import _make_strategy_resolver

            resolver = _make_strategy_resolver(session_factory=sm)
            service = MarketDataReplayService(
                market_data_port=DBMarketDataAdapter(),
                strategy_config_repo=StrategyConfigRepository(),
                strategy_resolver=resolver,
            )
            try:
                result = await service.replay(
                    symbols=symbols,
                    routine=routine,
                    as_of=as_of,
                    timeframe=timeframe,
                    lookback_bars=lookback_bars,
                )
            except ValueError as exc:
                typer.echo(f"[market-data replay] {exc}", err=True)
                raise typer.Exit(code=2) from exc

        # Print a compact table to stdout. NOT a structlog event - this
        # is operator-facing output.
        typer.echo(
            f"replay routine={result.routine} as_of={result.as_of.isoformat()} "
            f"bars_loaded={result.bars_loaded}"
        )
        typer.echo(
            f"{'symbol':<8} {'strategy':<14} {'v':>3} {'propose':<8} "
            f"{'side':<5} {'qty':>10} {'entry':>10} {'stop':>10}  rationale"
        )
        for row in result.rows:
            qty = "-" if row.quantity is None else f"{row.quantity}"
            entry = "-" if row.entry_price is None else f"{row.entry_price}"
            stop = "-" if row.stop_price is None else f"{row.stop_price}"
            side = row.side or "-"
            propose = "YES" if row.would_propose else "no"
            rationale = row.rationale[:80]
            typer.echo(
                f"{row.symbol:<8} {row.strategy_kind:<14} {row.strategy_version:>3} "
                f"{propose:<8} {side:<5} {qty:>10} {entry:>10} {stop:>10}  "
                f"{rationale}"
            )
    finally:
        await engine.dispose()


async def _run_sync(
    *,
    symbols_csv: str | None,
    timeframe: str,
    lookback_bars: int,
    tenant: str | None,
    invoked_by: str,
) -> None:
    """Construct ingestion service like the daemon does + invoke ``sync``."""
    import structlog

    from iguanatrader.contexts.trading.brokers.ib_async_client import (
        build_ib_async_client_from_env,
    )
    from iguanatrader.contexts.trading.market_data import MarketDataRateLimitedError
    from iguanatrader.contexts.trading.market_data.ibkr_ingestor import (
        IbAsyncMarketDataIngestor,
    )
    from iguanatrader.contexts.trading.market_data.repository import (
        MarketDataSyncAuditRepository,
    )
    from iguanatrader.contexts.trading.market_data.service import (
        MarketDataIngestionService,
    )
    from iguanatrader.persistence import engine_factory, session_factory
    from iguanatrader.shared.contextvars import session_var, tenant_id_var

    log = structlog.get_logger("iguanatrader.cli.market_data")

    default_watchlist = _parse_csv(
        os.environ.get("IGUANATRADER_DEFAULT_WATCHLIST_SYMBOLS"),
        default=["AAPL", "MSFT", "GOOGL"],
    )
    symbols = _parse_csv(symbols_csv, default=default_watchlist)
    if not symbols:
        typer.echo("No symbols supplied (CSV empty + no default watchlist).", err=True)
        raise typer.Exit(code=2)

    tenant_id = await resolve_tenant_id(tenant)

    engine = engine_factory(db_url())
    sm = session_factory(engine)

    ib_client = build_ib_async_client_from_env()
    ingestor = IbAsyncMarketDataIngestor(ib_client=ib_client)

    try:
        # The daemon connects its IB client via ``IBKRAdapter.start()``;
        # this standalone CLI path must connect explicitly or the ingestor
        # sees a disconnected client and every symbol fails "Not connected".
        # Resolve host/port/client_id from the same env the brokerage model
        # reads (IBKR_HOST / IBKR_PORT / IBKR_CLIENT_ID).
        ib_host = os.environ.get("IBKR_HOST", "127.0.0.1")
        ib_port = int(os.environ.get("IBKR_PORT", "4002"))
        ib_client_id = int(os.environ.get("IBKR_CLIENT_ID", "1"))
        await ib_client.connect_async(ib_host, ib_port, ib_client_id)
        async with sm() as session:
            tenant_id_var.set(tenant_id)
            session_var.set(session)
            audit_repo = MarketDataSyncAuditRepository()
            ingestion_service = MarketDataIngestionService(
                ingestor=ingestor,
                audit_repo=audit_repo,
            )
            try:
                result = await ingestion_service.sync(
                    symbols=symbols,
                    timeframe=timeframe,
                    lookback_bars=lookback_bars,
                    invoked_by=invoked_by,  # type: ignore[arg-type]
                )
                await session.commit()
            except MarketDataRateLimitedError as exc:
                await session.commit()  # rate-limited audit row still written
                typer.echo(f"[market-data] rate-limited: {exc.detail}", err=True)
                raise typer.Exit(code=2) from exc

        typer.echo(
            f"[market-data] {invoked_by} complete: "
            f"{len(result.successes)} success, "
            f"{len(result.failures)} failed, "
            f"{result.bars_written} bars written"
        )
        log.info(
            "cli.market_data.complete",
            invoked_by=invoked_by,
            successes=len(result.successes),
            failures=len(result.failures),
            bars_written=result.bars_written,
        )
    finally:
        with contextlib.suppress(Exception):  # best-effort teardown
            ib_client.disconnect()
        await engine.dispose()


__all__ = ["app"]
