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

    # Slice ``trading-daemon-scheduler-only-mode``: when the daemon
    # runs on infrastructure that does NOT have an IB Gateway / TWS
    # reachable (typical for a cloud VPS — the broker socket lives on
    # the operator's local machine), the ``IGUANATRADER_DAEMON_SCHEDULER_ONLY``
    # env flag dispatches to a minimal flow that only runs the I7
    # ingest cron. See :func:`_run_scheduler_only_daemon`.
    if os.environ.get("IGUANATRADER_DAEMON_SCHEDULER_ONLY", "false").lower() == "true":
        await _run_scheduler_only_daemon(
            tenant_id=tenant_id,
            log=log,
            shutdown_event=shutdown_event,
        )
        return

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
        from iguanatrader.contexts.trading.equity_snapshot_sweep import (
            EquitySnapshotSweepService,
        )
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
            EquitySnapshotRepository,
            StrategyConfigRepository,
        )
        from iguanatrader.contexts.trading.service import TradingService

        # Slice ``order-timeout-restart-reconcile``: read the order-
        # placement timeout from env (default 30s); operator tunes per
        # broker SLA. Validation lives in TradingService.__init__ —
        # invalid values surface as TypeError on construction.
        order_timeout_raw = os.environ.get("IGUANATRADER_ORDER_TIMEOUT_SECS", "30")
        try:
            order_timeout_secs = float(order_timeout_raw)
        except ValueError as exc:
            raise RuntimeError(
                f"IGUANATRADER_ORDER_TIMEOUT_SECS must be a float, got {order_timeout_raw!r}"
            ) from exc

        trading_service = TradingService(
            bus=bus,
            broker=broker,
            strategy_resolver=_make_strategy_resolver(session_factory=sessionmaker),
            order_timeout_secs=order_timeout_secs,
        )
        trading_service.register_subscriptions()

        # Slice ``order-timeout-restart-reconcile``: drain broker fills
        # the daemon missed while it was down BEFORE accepting new
        # propose / approve traffic. Idempotent at broker_fill_id; a
        # slightly-too-old since boundary is preferable to losing a
        # fill in a crash window.
        await trading_service.startup_reconcile()

        # Slice K1-followup-bus-subscriptions §3.1 — RiskService bridge
        # subscribes to ProposalCreated + emits ProposalRiskEvaluated.
        risk_service = RiskService(repository=RiskRepository(session=session), bus=bus)
        risk_service.register_subscriptions(bus)

        # Slice P1-followup-bus-subscriptions §3.1 — ApprovalService
        # bridge subscribes to ApprovalRequested (audit-write) + 3
        # outbound bridges (ApprovalProposal{Approved,Rejected,
        # TimedOut} → trading.ProposalApproved/Rejected). Closes the
        # last gap in the propose→risk→approve→execute chain.
        # Slice p1-followup-channel-fanout adds the dispatcher
        # injection (LogOnly v1; production push deferred to a future
        # operator slice when ops config is ready).
        from iguanatrader.contexts.approval.dispatcher import (
            build_channel_dispatcher_from_env,
        )

        approval_repository = ApprovalRepository()
        inner_channel_dispatcher = build_channel_dispatcher_from_env(
            repository=approval_repository,
        )

        # Slice ``llm-features-composition-wiring``: wrap the channel
        # dispatcher with auto-explain (A1) + subscribe auto-risk-review
        # (A2) + auto-journal (A3) + construct the I7 ingest scheduler.
        # See ``cli/llm_handler_wiring.py`` for the per-handler
        # production adapter shape. Best-effort across the board — a
        # missing ANTHROPIC_API_KEY surfaces as the wrapper's
        # swallowed-exception path so the bus still flows.
        from iguanatrader.cli._ingest_factories import (
            build_persist_drafts_closure,
            build_source_factories,
            load_watchlist_for_ingest,
        )
        from iguanatrader.cli.llm_handler_wiring import wire_llm_handlers
        from iguanatrader.contexts.research.synthesis.anthropic_client import (
            build_anthropic_llm_client_from_env,
        )
        from iguanatrader.contexts.trading.repository import (
            TradeProposalRepository,
            TradeRepository,
        )

        # I7 ingest scheduler inputs — sources, watchlist snapshot,
        # persist closure. See ``cli/_ingest_factories.py`` for the
        # 13-adapter factory map (sec_edgar/fred/openbb/ibkr/finnhub/
        # motley-fool/edgartools + the six previously-orphan
        # bea/bls/gdelt/openfda/vdem/wgi_world_bank).
        ingest_sources = build_source_factories()
        ingest_watchlist = await load_watchlist_for_ingest(sessionmaker=sessionmaker)
        ingest_persist_drafts = build_persist_drafts_closure(sessionmaker=sessionmaker)

        wrapped_channel_dispatcher = wire_llm_handlers(
            bus=bus,
            scheduler=scheduler,
            llm_client=build_anthropic_llm_client_from_env(),
            inner_dispatcher=inner_channel_dispatcher,
            trade_repo=TradeRepository(),
            proposal_repo=TradeProposalRepository(),
            session_factory=sessionmaker,
            ingest_sources=ingest_sources,
            ingest_watchlist=ingest_watchlist,
            ingest_persist_drafts=ingest_persist_drafts,
        )

        approval_service = ApprovalService(
            repository=approval_repository,
            message_bus=bus,
            channel_dispatcher=wrapped_channel_dispatcher,
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

        # Slice equity-snapshot-daemon: 15-min cron that drives the
        # rolling drawdown window K1 reads. Without this the snapshot
        # row only lands on trade close, leaving max-drawdown
        # protection silently inert between fills.
        equity_snapshot_sweep_service = EquitySnapshotSweepService(
            broker=broker,
            equity_repo=EquitySnapshotRepository(),
            bus=bus,
        )

        # Slice exit-classification-stop-hit-sweep: 1-min cron that
        # watches every open trade for stop_price / target_price
        # breaches and publishes CloseTradeRequested. Closes the
        # auto-close loop that K1's stoploss_guard depends on.
        from iguanatrader.contexts.risk.stop_hit_sweep import StopHitSweepService

        stop_hit_sweep_service = StopHitSweepService(
            session=session,
            market_data_port=market_data_port,
            bus=bus,
        )

        orchestration_repo = OrchestrationRepository()
        orchestration_service = OrchestrationService(repository=orchestration_repo)
        # Side-effect: registers cron JobSpecs on the scheduler (4 propose
        # routines + 5th market_data_sync routine wired by T4-followup
        # + equity_snapshot_sweep + stop_hit_sweep wired here).
        await orchestration_service.bootstrap_routines(
            scheduler=scheduler,
            trading_service=trading_service,
            watchlist_symbols=watchlist_symbols,
            market_data_port=market_data_port,
            strategy_config_repo=strategy_config_repo,
            ingestion_service=ingestion_service,
            equity_snapshot_sweep_service=equity_snapshot_sweep_service,
            stop_hit_sweep_service=stop_hit_sweep_service,
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


async def _run_scheduler_only_daemon(
    *,
    tenant_id: UUID,
    log: Any,
    shutdown_event: asyncio.Event,
) -> None:
    """Minimal daemon flow: only the I7 ingest scheduler.

    Slice ``trading-daemon-scheduler-only-mode``. Used on infrastructure
    where the IB Gateway / TWS is unreachable (typical VPS deployment).
    Skips broker construction entirely — only the I7 ingest cron is
    registered, so research_facts stay fresh without any trading
    state-machine wiring.

    Flow:

    1. Build APScheduler + new MessageBus (in-process, unused but
       :class:`IngestSchedulerService` doesn't currently need it).
    2. Build the 13-adapter source factory + watchlist snapshot +
       persist closure (via ``cli/_ingest_factories``).
    3. Register the cron jobs.
    4. Start the scheduler + block on SIGTERM.
    """
    from iguanatrader.cli._ingest_factories import (
        build_persist_drafts_closure,
        build_source_factories,
        load_watchlist_for_ingest,
    )
    from iguanatrader.contexts.orchestration.apscheduler_adapter import (
        build_apscheduler_adapter_from_env,
    )
    from iguanatrader.contexts.research.ingest_scheduler import (
        IngestRunRecorder,
        IngestSchedulerService,
    )
    from iguanatrader.persistence import engine_factory, session_factory
    from iguanatrader.shared.contextvars import session_var, tenant_id_var

    log.info("trading.daemon.scheduler_only.boot", tenant_id=str(tenant_id))
    engine = engine_factory(db_url())
    sessionmaker = session_factory(engine)
    scheduler = build_apscheduler_adapter_from_env()

    async with sessionmaker() as session:
        tenant_id_var.set(tenant_id)
        session_var.set(session)

        ingest_sources = build_source_factories()
        ingest_watchlist = await load_watchlist_for_ingest(sessionmaker=sessionmaker)
        ingest_persist_drafts = build_persist_drafts_closure(sessionmaker=sessionmaker)

        recorder = IngestRunRecorder(session_provider=sessionmaker)
        ingest_scheduler = IngestSchedulerService(recorder=recorder)
        specs = ingest_scheduler.bootstrap_ingest_routines(
            scheduler=scheduler,
            watchlist=ingest_watchlist,
            sources=ingest_sources,
            persist_drafts=ingest_persist_drafts,
        )
        log.info(
            "trading.daemon.scheduler_only.ingest_jobs_registered",
            jobs=len(specs),
        )

        await scheduler.start()
        log.info("trading.daemon.scheduler_only.ready")

        await shutdown_event.wait()

        log.info("trading.daemon.scheduler_only.shutdown.draining")
        try:
            await scheduler.shutdown()
        except Exception as exc:
            log.warning(
                "trading.daemon.scheduler_only.scheduler.shutdown_failed",
                error=str(exc),
            )

    await engine.dispose()
    log.info("trading.daemon.scheduler_only.shutdown.complete")


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
