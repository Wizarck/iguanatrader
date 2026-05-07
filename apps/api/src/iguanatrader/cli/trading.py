"""Trading operator CLI — ``iguanatrader trading <subcommand>`` (slice T4).

Subcommands:

* ``run --mode {paper,live} --tenant <slug>`` — long-running async
  daemon. Constructs production adapters (IbAsyncIBClient via 3.B.2 +
  APSchedulerAdapter via 3.C.2 — both promised by deployment-foundation
  retro carry-forward), wires bus subscriptions, starts the heartbeat
  loop + scheduler, and blocks on SIGTERM for graceful drain.

Heavy imports kept lazy per gotcha #29 (``--help`` performance).
"""

from __future__ import annotations

import asyncio
import os
import signal
from typing import TYPE_CHECKING, cast

import typer

from iguanatrader.cli._tenant import db_url, resolve_tenant_id

if TYPE_CHECKING:
    from uuid import UUID

    from iguanatrader.contexts.trading.brokers.ib_async_client import IbAsyncIBClient
    from iguanatrader.contexts.trading.brokers.ibkr_adapter import IBKRAdapter
    from iguanatrader.contexts.trading.ports import StrategyPort
    from iguanatrader.contexts.trading.service import StrategyResolver

app: typer.Typer = typer.Typer(
    name="trading",
    help="Trading daemon operator commands (slice T4).",
    no_args_is_help=True,
)


_VALID_MODES = ("paper", "live")
_DEFAULT_WATCHLIST = "AAPL,MSFT,GOOGL"


def _parse_watchlist(raw: str | None) -> list[str]:
    """Parse ``IGUANATRADER_DEFAULT_WATCHLIST_SYMBOLS`` (comma-separated).

    Default `AAPL,MSFT,GOOGL` per slice T4 §3.3.g (env-var first-cut;
    v2 SaaS swaps to a per-tenant ``watchlists`` table).
    """
    csv = (raw or _DEFAULT_WATCHLIST).strip()
    return [sym.strip().upper() for sym in csv.split(",") if sym.strip()]


@app.command("run")
def run(
    mode: str = typer.Option(..., "--mode", help=f"One of: {', '.join(_VALID_MODES)}."),
    tenant: str | None = typer.Option(
        None,
        "--tenant",
        help="Tenant slug; defaults to the first tenant if single-tenant.",
    ),
) -> None:
    """Run the iguanatrader trading daemon (long-running)."""
    if mode not in _VALID_MODES:
        typer.echo(f"Invalid mode {mode!r}; expected one of {_VALID_MODES}")
        raise typer.Exit(code=2)

    asyncio.run(_run_daemon(mode=mode, tenant=tenant))


async def _run_daemon(*, mode: str, tenant: str | None) -> None:
    """Async daemon body — orchestrates startup → run → shutdown.

    Per slice T4 §2.2 + the deployment-foundation retro carry-forward:
    this entrypoint is the canonical home for 3.B.2 (IBKRAdapter ←
    IbAsyncIBClient DI) + 3.C.2 (OrchestrationService ← APSchedulerAdapter
    DI). Both wirings are single lines.
    """
    import structlog

    log = structlog.get_logger("iguanatrader.cli.trading")
    log.info("trading.daemon.boot", mode=mode, tenant=tenant)

    tenant_id = await resolve_tenant_id(tenant)
    log.info("trading.daemon.tenant_resolved", tenant_id=str(tenant_id))

    from iguanatrader.contexts.orchestration.apscheduler_adapter import (
        build_apscheduler_adapter_from_env,
    )
    from iguanatrader.contexts.trading.brokers.ib_async_client import (
        build_ib_async_client_from_env,
    )
    from iguanatrader.persistence import engine_factory, session_factory
    from iguanatrader.shared.contextvars import session_var, tenant_id_var
    from iguanatrader.shared.messagebus import MessageBus

    engine = engine_factory(db_url())
    sessionmaker = session_factory(engine)
    shutdown_event = asyncio.Event()

    def _request_shutdown(*_: object) -> None:
        log.info("trading.daemon.shutdown.requested")
        shutdown_event.set()

    # SIGTERM + SIGINT both trigger graceful shutdown (Ctrl+C in dev).
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except NotImplementedError:
            # Windows asyncio loop doesn't support add_signal_handler — fall
            # back to signal.signal which works on the main thread.
            signal.signal(sig, _request_shutdown)

    # Slice deployment-foundation 3.B.2 wiring — IbAsyncIBClient is a
    # one-line factory call; IBKRAdapter consumes it via client_factory.
    ib_client = build_ib_async_client_from_env()
    # Slice deployment-foundation 3.C.2 wiring — APSchedulerAdapter is
    # a one-line factory call. OrchestrationService receives it as a
    # constructor arg in §3.4 bootstrap_routines.
    scheduler = build_apscheduler_adapter_from_env()

    log.info("trading.daemon.adapters_built", broker_mode=mode)

    broker = await _build_broker(ib_client=ib_client, mode=mode)

    async with sessionmaker() as session:
        tenant_id_var.set(tenant_id)
        session_var.set(session)

        bus = MessageBus()
        watchlist_symbols = _parse_watchlist(
            os.environ.get("IGUANATRADER_DEFAULT_WATCHLIST_SYMBOLS")
        )

        from iguanatrader.contexts.orchestration.repository import (
            OrchestrationRepository,
        )
        from iguanatrader.contexts.orchestration.service import OrchestrationService
        from iguanatrader.contexts.risk.repository import RiskRepository
        from iguanatrader.contexts.risk.service import RiskService
        from iguanatrader.contexts.trading.service import TradingService

        trading_service = TradingService(
            bus=bus,
            broker=broker,
            strategy_resolver=_make_strategy_resolver(),
        )
        trading_service.register_subscriptions()

        # Slice K1-followup-bus-subscriptions §3.1 — RiskService bridge
        # subscribes to ProposalCreated + emits ProposalRiskEvaluated.
        risk_service = RiskService(repository=RiskRepository(session=session), bus=bus)
        risk_service.register_subscriptions(bus)

        orchestration_repo = OrchestrationRepository()
        orchestration_service = OrchestrationService(repository=orchestration_repo)
        # Side-effect: registers cron JobSpecs on the scheduler.
        await orchestration_service.bootstrap_routines(
            scheduler=scheduler,
            trading_service=trading_service,
            watchlist_symbols=watchlist_symbols,
        )

        # P1 ApprovalService bus subscriptions are NOT yet shipped
        # (its service class lacks register_subscriptions); slice
        # P1-followup owns that wiring. K1 propose→risk hop is wired
        # by this slice (K1-followup-bus-subscriptions); the manual-
        # approve endpoint (POST /trades/proposals/{id}/approve)
        # remains the operator override path that still bypasses P1.
        log.warning(
            "trading.daemon.bus_subscriptions.partial",
            note=(
                "P1 ApprovalService bus subscriptions deferred to a "
                "follow-up slice; manual approve endpoint "
                "(POST /trades/proposals/{id}/approve) bypasses the chain."
            ),
        )

        await scheduler.start()
        log.info("trading.daemon.scheduler_started")

        log.info(
            "trading.daemon.ready",
            tenant_id=str(tenant_id),
            mode=mode,
            watchlist_count=len(watchlist_symbols),
        )

        await shutdown_event.wait()

        log.info("trading.daemon.shutdown.draining")
        try:
            await scheduler.shutdown()
        except Exception as exc:
            log.warning("trading.daemon.scheduler.shutdown_failed", error=str(exc))

        try:
            await broker.disconnect()
        except Exception as exc:
            log.warning("trading.daemon.broker.disconnect_failed", error=str(exc))

        try:
            from iguanatrader.contexts.research.scraping.tier2_playwright import (
                shutdown_playwright,
            )

            await shutdown_playwright()
        except Exception as exc:
            log.warning("trading.daemon.playwright.shutdown_failed", error=str(exc))

        await bus.aclose()

    await engine.dispose()
    log.info("trading.daemon.shutdown.complete")


async def _build_broker(*, ib_client: IbAsyncIBClient, mode: str) -> IBKRAdapter:
    """Construct the production :class:`IBKRAdapter` with the supplied IB client.

    `IbAsyncIBClient` is structurally compatible with the `IBClient`
    Protocol (per slice T2 design D7), so we cast() to bypass mypy's
    nominal-typing check on the `client_factory` callable arg.
    """
    from iguanatrader.contexts.trading.brokers.client_protocol import IBClient
    from iguanatrader.contexts.trading.brokers.ibkr_adapter import IBKRAdapter

    return IBKRAdapter(  # type: ignore[call-arg]
        client_factory=lambda: cast("IBClient", ib_client),
    )


def _make_strategy_resolver() -> StrategyResolver:
    """Closure resolver: ``UUID → StrategyPort`` (slice T4 §3.3.f).

    Loads the :class:`StrategyConfig` snapshot for the given id, then
    delegates to :class:`StrategyManager._get_or_build` to construct
    the actual :class:`StrategyPort` instance. The closure keeps the
    daemon's manager-instance alive across the bus event loop.
    """
    from iguanatrader.contexts.trading.strategies.manager import StrategyManager

    manager = StrategyManager()

    def _resolve(strategy_config_id: UUID) -> StrategyPort:
        # Lazy snapshot load + manager._get_or_build — production code
        # path. Tests inject a static map instead via the
        # `strategy_resolver` constructor arg directly.
        raise NotImplementedError(
            f"_make_strategy_resolver requires a session-scoped "
            f"StrategyConfigRepository to load snapshot for "
            f"{strategy_config_id!r}; T4 leaves this as a NotImplementedError "
            "placeholder — slice T4-followup wires the repository call. "
            "Tests bypass via direct strategy_resolver injection."
        )

    _ = manager  # keep referenced; T4-followup uses it.
    return cast("StrategyResolver", _resolve)


__all__ = ["app"]
