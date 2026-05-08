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
from typing import TYPE_CHECKING, Any, cast

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

        from iguanatrader.contexts.approval.repository import ApprovalRepository
        from iguanatrader.contexts.approval.service import ApprovalService
        from iguanatrader.contexts.orchestration.repository import (
            OrchestrationRepository,
        )
        from iguanatrader.contexts.orchestration.service import OrchestrationService
        from iguanatrader.contexts.risk.repository import RiskRepository
        from iguanatrader.contexts.risk.service import RiskService
        from iguanatrader.contexts.trading.market_data.db import DBMarketDataAdapter
        from iguanatrader.contexts.trading.market_data.ibkr_ingestor import (
            IbAsyncMarketDataIngestor,
        )
        from iguanatrader.contexts.trading.market_data.repository import (
            MarketDataSyncAuditRepository,
        )
        from iguanatrader.contexts.trading.market_data.service import (
            MarketDataIngestionService,
        )
        from iguanatrader.contexts.trading.repository import (
            StrategyConfigRepository,
        )
        from iguanatrader.contexts.trading.service import TradingService

        trading_service = TradingService(
            bus=bus,
            broker=broker,
            strategy_resolver=_make_strategy_resolver(session_factory=sessionmaker),
        )
        trading_service.register_subscriptions()

        # Slice K1-followup-bus-subscriptions §3.1 — RiskService bridge
        # subscribes to ProposalCreated + emits ProposalRiskEvaluated.
        risk_service = RiskService(repository=RiskRepository(session=session), bus=bus)
        risk_service.register_subscriptions(bus)

        # Slice P1-followup-bus-subscriptions §3.1 — ApprovalService
        # bridge subscribes to ApprovalRequested (audit-write) + 3
        # outbound bridges (ApprovalProposal{Approved,Rejected,
        # TimedOut} → trading.ProposalApproved/Rejected). Closes the
        # last gap in the propose→risk→approve→execute chain.
        approval_service = ApprovalService(
            repository=ApprovalRepository(),
            message_bus=bus,
        )
        approval_service.register_subscriptions(bus)

        # Slice T4-followup-market-data §2.13 — market-data subsystem.
        # DBMarketDataAdapter reads bars from `market_data_bars` table;
        # IbAsyncMarketDataIngestor SHARES `ib_client` with the broker
        # (per design Open Question 1) and runs daily via the new
        # `market_data_sync` cron routine wired in bootstrap_routines.
        market_data_port = DBMarketDataAdapter()
        strategy_config_repo = StrategyConfigRepository()
        ingestor = IbAsyncMarketDataIngestor(ib_client=ib_client)
        audit_repo = MarketDataSyncAuditRepository()
        ingestion_service = MarketDataIngestionService(
            ingestor=ingestor,
            audit_repo=audit_repo,
        )

        # Slice R6 hindsight-integration §7 — narrative recall bank.
        # build_hindsight_adapter_from_env() returns InMemoryHindsightAdapter
        # if IGUANATRADER_HINDSIGHT_URL unset (dev/CI safe). Always-on
        # retain via bus subscription on ResearchBriefSynthesized.
        from iguanatrader.contexts.research.hindsight.http_adapter import (
            build_hindsight_adapter_from_env,
        )
        from iguanatrader.contexts.research.hindsight.retain_handler import (
            HindsightRetainHandler,
        )
        from iguanatrader.contexts.research.repository import (
            ResearchRepository,
        )

        hindsight = build_hindsight_adapter_from_env()
        research_repo = ResearchRepository()
        hindsight_retain = HindsightRetainHandler(
            hindsight=hindsight,
            repository=research_repo,
        )
        hindsight_retain.register_subscriptions(bus)

        orchestration_repo = OrchestrationRepository()
        orchestration_service = OrchestrationService(repository=orchestration_repo)
        # Side-effect: registers cron JobSpecs on the scheduler (4 propose
        # routines + 5th market_data_sync routine wired by T4-followup).
        await orchestration_service.bootstrap_routines(
            scheduler=scheduler,
            trading_service=trading_service,
            watchlist_symbols=watchlist_symbols,
            market_data_port=market_data_port,
            strategy_config_repo=strategy_config_repo,
            ingestion_service=ingestion_service,
        )

        # K1 (PR #103) + P1 (this slice) bus-bridge follow-ups close
        # the propose→risk→approve→execute chain end-to-end.
        log.info("trading.daemon.bus_subscriptions.complete")

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


def _make_strategy_resolver(
    *,
    session_factory: Any,
) -> StrategyResolver:
    """Async closure resolver: ``UUID → StrategyPort`` (slice T4-followup-market-data §2.10).

    Loads a fresh :class:`StrategyConfig` per propose call via
    :class:`StrategyConfigRepository` (session-scoped), projects to a
    :class:`StrategyConfigSnapshot`, then delegates to
    :meth:`StrategyManager._get_or_build` for hot-reload-safe instance
    construction. The manager + cache are closure-captured across calls.
    """
    from iguanatrader.contexts.trading.ports import StrategyConfigSnapshot
    from iguanatrader.contexts.trading.repository import StrategyConfigRepository
    from iguanatrader.contexts.trading.strategies.manager import StrategyManager
    from iguanatrader.shared.contextvars import session_var

    manager = StrategyManager()

    async def _resolve(strategy_config_id: UUID) -> StrategyPort:
        async with session_factory() as session:
            session_var.set(session)
            repo = StrategyConfigRepository()
            row = await repo.get_by_id(strategy_config_id)
            if row is None:
                raise LookupError(f"StrategyConfig {strategy_config_id} not found")
            snapshot = StrategyConfigSnapshot(
                id=row.id,
                tenant_id=row.tenant_id,
                strategy_kind=row.strategy_kind,
                symbol=row.symbol,
                params=dict(row.params),
                enabled=row.enabled,
                version=row.version,
            )
            strategy = manager._get_or_build(snapshot)
            if strategy is None:
                raise LookupError(f"Unknown strategy_kind {row.strategy_kind!r}")
            return cast("StrategyPort", strategy)

    return cast("StrategyResolver", _resolve)


__all__ = ["app"]
