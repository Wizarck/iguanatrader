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
from typing import TYPE_CHECKING, Any, Literal, cast

import typer

from iguanatrader.cli._tenant import db_url, resolve_tenant_id

if TYPE_CHECKING:
    from uuid import UUID

    from iguanatrader.contexts.risk.position_review import PositionReviewResult
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


# ----------------------------------------------------------------------
# #15: LIVE-daemon paper-history gate (AGENTS.md §7 override 2026-04-28)
# ----------------------------------------------------------------------
# The system ALWAYS recommends paper trading. Starting LIVE for a tenant with
# NO recorded paper-trading history requires BOTH --confirm-live AND
# --i-understand-the-risks; absence of a paper record emits a WARNING (it does
# not block once the risk is acknowledged) and records the override decision in
# audit_log with the literal acknowledgment text. A durable per-boot
# session-start row (the ``.paper`` variant is what a later LIVE start reads as
# paper history) also satisfies the "immutable execution logs" hard rule.
_LIVE_OVERRIDE_EVENT = "trading.daemon.live_override.no_paper_history"
_RISK_ACK_TEXT = (
    "I understand this starts LIVE real-money trading for a tenant with no "
    "recorded paper-trading history, and I accept the risk."
)


def _session_started_event(mode: str) -> str:
    return f"trading.daemon.session.started.{mode}"


#: The event a prior PAPER boot writes; the LIVE gate reads it as "paper history".
_PAPER_SESSION_EVENT = _session_started_event("paper")


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


async def _enforce_live_paper_history_gate(
    *, audit_repo: Any, mode: str, i_understand_the_risks: bool, log: Any
) -> None:
    """Gate LIVE startup on paper-trading history (#15 / AGENTS.md §7).

    No-op for paper mode and for LIVE when the tenant has prior paper history.
    For LIVE WITHOUT paper history: requires ``--i-understand-the-risks`` (or
    the env equivalent) — blocks (exit 2) if absent, else emits a WARNING and
    records the override decision in ``audit_log``. Must run inside an open
    session + tenant scope (it reads/writes ``audit_log`` via the ambient
    unit of work).
    """
    if mode != "live":
        return
    if await audit_repo.event_exists(_PAPER_SESSION_EVENT):
        return  # prior paper history → --confirm-live alone is sufficient
    acknowledged = i_understand_the_risks or _env_truthy("IGUANATRADER_I_UNDERSTAND_THE_RISKS")
    if not acknowledged:
        log.error("trading.daemon.live_blocked.no_paper_history")
        typer.echo(
            "Refusing to start LIVE: this tenant has NO recorded paper-trading "
            "history. Paper trading is strongly recommended first. To proceed "
            "anyway, re-run with --i-understand-the-risks (or set "
            "IGUANATRADER_I_UNDERSTAND_THE_RISKS=true)."
        )
        raise typer.Exit(code=2)
    log.warning(
        "trading.daemon.live_override.no_paper_history",
        risk_acknowledgment=_RISK_ACK_TEXT,
    )
    typer.echo(
        "WARNING: starting LIVE real-money trading with NO paper-trading "
        "history for this tenant. Recorded as an acknowledged override. "
        f"Acknowledgment: {_RISK_ACK_TEXT}"
    )
    await _insert_audit_row(
        audit_repo,
        event=_LIVE_OVERRIDE_EVENT,
        metadata={"mode": "live", "risk_acknowledgment": _RISK_ACK_TEXT},
    )


async def _record_daemon_session_start(*, audit_repo: Any, mode: str) -> None:
    """Record a durable session-start audit row (#15 + immutable-logs rule)."""
    await _insert_audit_row(
        audit_repo,
        event=_session_started_event(mode),
        metadata={"mode": mode},
    )


async def _insert_audit_row(audit_repo: Any, *, event: str, metadata: dict[str, Any]) -> None:
    from uuid import uuid4

    from iguanatrader.contexts.observability.models import AuditLog

    await audit_repo.insert_for_tenant(
        AuditLog(id=uuid4(), actor_kind="system", event=event, metadata_json=metadata)
    )


@app.command("run")
def run(
    mode: str = typer.Option(..., "--mode", help=f"One of: {', '.join(_VALID_MODES)}."),
    tenant: str | None = typer.Option(
        None,
        "--tenant",
        help="Tenant slug; defaults to the first tenant if single-tenant.",
    ),
    confirm_live: bool = typer.Option(
        False,
        "--confirm-live",
        help="Required to start the LIVE (real-money) daemon. Ignored in paper mode.",
    ),
    i_understand_the_risks: bool = typer.Option(
        False,
        "--i-understand-the-risks",
        help=(
            "Required (with --confirm-live) to start LIVE when this tenant has "
            "NO prior paper-trading history. Ignored in paper mode and when "
            "paper history exists."
        ),
    ),
) -> None:
    """Run the iguanatrader trading daemon (long-running)."""
    if mode not in _VALID_MODES:
        typer.echo(f"Invalid mode {mode!r}; expected one of {_VALID_MODES}")
        raise typer.Exit(code=2)

    # #15: live mode places real-money orders. Refuse to start it without an
    # explicit confirmation — the ``--confirm-live`` flag, or the
    # ``IGUANATRADER_CONFIRM_LIVE`` env truthy for non-interactive (k8s /
    # systemd) deploys. Paper mode is unaffected.
    if mode == "live":
        env_confirm = os.environ.get("IGUANATRADER_CONFIRM_LIVE", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if not (confirm_live or env_confirm):
            typer.echo(
                "Refusing to start the LIVE trading daemon without confirmation. "
                "Re-run with --confirm-live (or set IGUANATRADER_CONFIRM_LIVE=true) "
                "once you understand this places real-money orders."
            )
            raise typer.Exit(code=2)

    asyncio.run(
        _run_daemon(
            mode=mode,
            tenant=tenant,
            i_understand_the_risks=i_understand_the_risks,
        )
    )


@app.command("positions-review")
def positions_review(
    mode: str = typer.Option(
        "paper", "--mode", help=f"Broker mode to connect for the read: {', '.join(_VALID_MODES)}."
    ),
    tenant: str | None = typer.Option(
        None, "--tenant", help="Tenant slug; defaults to the first tenant if single-tenant."
    ),
) -> None:
    """Show open positions + the protective stop / take-profit orders ACTUALLY
    resting at the broker, with any divergence from the DB-intended levels.

    Read-only: connects to the broker, reads positions + the working-order
    book, reconciles them against each open trade's intended stop/target, and
    prints the result. Never places, cancels, or closes anything.
    """
    if mode not in _VALID_MODES:
        typer.echo(f"Invalid mode {mode!r}; expected one of {_VALID_MODES}")
        raise typer.Exit(code=2)
    asyncio.run(_run_positions_review(mode=mode, tenant=tenant))


async def _run_positions_review(*, mode: str, tenant: str | None) -> None:
    from iguanatrader.contexts.risk.position_review import PositionReviewService
    from iguanatrader.contexts.risk.trailing_stop_repository import (
        TrailingStopAuditRepository,
    )
    from iguanatrader.contexts.trading.brokers.ib_async_client import (
        build_ib_async_client_from_env,
    )
    from iguanatrader.persistence import engine_factory, session_factory
    from iguanatrader.shared.contextvars import session_var, tenant_id_var

    tenant_id = await resolve_tenant_id(tenant)
    ib_client = build_ib_async_client_from_env()
    broker = await _build_broker(ib_client=ib_client, mode=mode, tenant_id=tenant_id)
    await broker.connect()
    try:
        engine = engine_factory(db_url())
        sessionmaker = session_factory(engine)
        async with sessionmaker() as session:
            tenant_id_var.set(tenant_id)
            session_var.set(session)
            service = PositionReviewService(
                broker=broker,
                session=session,
                trailing_audit_repo=TrailingStopAuditRepository(),
            )
            result = await service.review()
        _print_position_review(result)
    finally:
        await broker.disconnect()


def _fmt(value: object | None) -> str:
    return "—" if value is None else str(value)


def _print_position_review(result: PositionReviewResult) -> None:
    typer.echo(
        f"Open positions: {len(result.reviews)} | broker positions: "
        f"{result.broker_positions_read} | working orders: "
        f"{result.broker_working_orders_read} | divergences: "
        f"{result.divergences_detected}"
    )
    if not result.reviews:
        typer.echo("  (no open positions)")
        return
    for r in result.reviews:
        typer.echo("")
        typer.echo(
            f"  {r.symbol}  {r.side.upper()}  qty={r.quantity}"
            f"  broker_qty={_fmt(r.broker_quantity)}"
            f"  avg={_fmt(r.average_price)}  uPnL={_fmt(r.unrealized_pnl)}"
        )
        rest_stop = (
            f"{r.resting_stop.order_type}@{_fmt(r.resting_stop.level)} ({r.resting_stop.status})"
            if r.resting_stop is not None
            else "NONE"
        )
        rest_tgt = (
            f"{r.resting_target.order_type}@{_fmt(r.resting_target.level)}"
            f" ({r.resting_target.status})"
            if r.resting_target is not None
            else "NONE"
        )
        typer.echo(f"    stop:   intended={r.intended_stop}  resting={rest_stop}")
        typer.echo(f"    target: intended={_fmt(r.intended_target)}  resting={rest_tgt}")
        if r.divergences:
            typer.echo(f"    ⚠ divergences: {', '.join(r.divergences)}")


async def _run_daemon(
    *, mode: str, tenant: str | None, i_understand_the_risks: bool = False
) -> None:
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
    from iguanatrader.shared.contextvars import (
        session_scoped_delivery,
        session_var,
        tenant_id_var,
    )
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

    # #15: gate LIVE startup on paper-trading history BEFORE connecting the
    # broker (so a blocked LIVE start never opens a real-money socket). Uses a
    # short-lived session + tenant scope; the long-lived daemon session opens
    # further below. Also records a durable per-boot session-start audit row.
    async with sessionmaker() as gate_session:
        tenant_id_var.set(tenant_id)
        session_var.set(gate_session)
        from iguanatrader.contexts.observability.repository import AuditLogRepository

        gate_audit = AuditLogRepository()
        await _enforce_live_paper_history_gate(
            audit_repo=gate_audit,
            mode=mode,
            i_understand_the_risks=i_understand_the_risks,
            log=log,
        )
        await _record_daemon_session_start(audit_repo=gate_audit, mode=mode)
        await gate_session.commit()

    broker = await _build_broker(ib_client=ib_client, mode=mode, tenant_id=tenant_id)
    # Open the IBKR connection before any broker call. Without this the
    # adapter's ``_client`` stays None and the first broker use in
    # ``startup_reconcile`` → ``reconcile_fills`` raises
    # IntegrationError("client not connected"), crash-looping the daemon
    # (the full-mode path was never exercised end-to-end before).
    await broker.connect()

    async with sessionmaker() as session:
        tenant_id_var.set(tenant_id)
        session_var.set(session)

        # Audit #2/#27/#29: deliver every bus event in its OWN session +
        # commit boundary with publish-after-commit (the transactional
        # outbox), instead of every worker sharing this long-lived session.
        # This is what makes the execution ledger durable (#2) and the
        # kill-switch auto-activation commit at trip time (#27), and removes
        # the cross-handler session aliasing (#29). Bus-driven services
        # resolve their session from session_var at call time, so a single
        # service instance rides whichever per-delivery session the
        # middleware binds. The ambient ``session`` above remains the unit
        # of work for the sequential daemon STARTUP steps only; the cron
        # sweeps now each run on their own fresh per-tick session via
        # ``_sweep_unit_of_work`` (closes the #29 cron-side hazard).
        bus = MessageBus()
        bus.set_delivery_middleware(session_scoped_delivery(sessionmaker, bus))
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
        from iguanatrader.contexts.trading.daemon_lifecycle import (
            DaemonLifecycleService,
        )
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
            TradingModeRepository,
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

        # Slice #5: wire the authoritative kill-switch reader so the
        # execute-on-approval boundary re-checks the DB cache before
        # placing a live order (the in-memory flag is never set in
        # production because ``halt_handler`` is unsubscribed). Reads the
        # same per-tenant cache ``RiskService.evaluate_proposal`` uses.
        async def _kill_switch_reader(check_tenant_id: UUID) -> bool:
            # No explicit session: this runs inside execute_on_approval_handler,
            # a bus handler, so it resolves the per-delivery session the
            # middleware bound (which sees the committed kill-switch cache) —
            # not the long-lived daemon session (#29).
            return await RiskRepository().load_kill_switch_state(check_tenant_id)

        # Slice ``propose-dedup``: the pending-proposal flood guard re-emits
        # a proposal only after its prior approval card has had its full
        # decision window, so default the dedup window to the approval
        # timeout. Operator overrides via
        # ``IGUANATRADER_PROPOSE_DEDUP_WINDOW_SECONDS``.
        dedup_window_raw = os.environ.get(
            "IGUANATRADER_PROPOSE_DEDUP_WINDOW_SECONDS",
            os.environ.get("IGUANATRADER_DEFAULT_APPROVAL_TIMEOUT_SECONDS", "1800"),
        )
        try:
            propose_dedup_window_secs = max(1, int(dedup_window_raw))
        except ValueError as exc:
            raise RuntimeError(
                "IGUANATRADER_PROPOSE_DEDUP_WINDOW_SECONDS must be an int, "
                f"got {dedup_window_raw!r}"
            ) from exc

        trading_service = TradingService(
            bus=bus,
            broker=broker,
            strategy_resolver=_make_strategy_resolver(session_factory=sessionmaker),
            order_timeout_secs=order_timeout_secs,
            kill_switch_reader=_kill_switch_reader,
            propose_dedup_window_secs=propose_dedup_window_secs,
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
        # No explicit session (#27/#29): the repository resolves the
        # per-delivery session the bus middleware binds, so the kill-switch
        # auto-activation commits at trip time instead of riding the shared
        # session's incidental later commit.
        risk_service = RiskService(repository=RiskRepository(), bus=bus)
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

        # Slice ``hindsight-producer-on-trade-close``: hoist the
        # Hindsight adapter construction ahead of wire_llm_handlers
        # so the A3 auto-journal handler can push trade-close
        # narratives into the recall bank. Pre-slice the adapter was
        # only consumed by HindsightRetainHandler (brief-synthesized
        # path); the A3 path used a no-op stub.
        from iguanatrader.contexts.research.hindsight.http_adapter import (
            build_hindsight_adapter_from_env,
        )

        hindsight = build_hindsight_adapter_from_env()

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
            hindsight_client=hindsight,
        )

        approval_service = ApprovalService(
            repository=approval_repository,
            message_bus=bus,
            channel_dispatcher=wrapped_channel_dispatcher,
        )
        approval_service.register_subscriptions(bus)

        # Slice ``brief-refresh-daemon-cron``: optional per-symbol research
        # brief refresh that feeds the LLM decision gate the latest
        # fundamental context. OFF by default
        # (IGUANATRADER_BRIEF_REFRESH_ENABLED) — enabling it spends an OpenBB
        # fetch + one LLM synthesis per watchlist symbol once a day pre-market.
        # Passing ``bus`` makes each synthesis publish ResearchBriefSynthesized
        # so the subscribed HindsightRetainHandler retains the fresh thesis.
        brief_refresh_service: Any | None = None
        if _env_truthy("IGUANATRADER_BRIEF_REFRESH_ENABLED"):
            from iguanatrader.contexts.research.factory import build_brief_service
            from iguanatrader.contexts.research.repository import ResearchRepository

            brief_refresh_service = build_brief_service(
                ResearchRepository(), hindsight=hindsight, bus=bus
            )

        # Slice ``mcp-hitl-approvals`` §6 — push execution + close-out
        # updates to the operator's authorised senders (OrderFilled +
        # TradeClosed). Best-effort; only wired when Hermes is configured
        # (HERMES_BASE_URL + HERMES_HMAC_SECRET), else a no-op.
        from iguanatrader.contexts.approval.execution_notifier import (
            build_execution_notifier_from_env,
        )

        execution_notifier = build_execution_notifier_from_env()
        if execution_notifier is not None:
            execution_notifier.register(bus)

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

        # Slice R6 hindsight-integration §7 — narrative recall bank
        # for brief-synthesized events. The adapter itself was built
        # above (slice ``hindsight-producer-on-trade-close``) so the
        # A3 auto-journal could share it; here we attach the
        # brief-side retain handler that also rides on the same port.
        from iguanatrader.contexts.research.hindsight.retain_handler import (
            HindsightRetainHandler,
        )
        from iguanatrader.contexts.research.repository import (
            ResearchRepository,
        )

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
        from iguanatrader.contexts.risk.trailing_stop_repository import (
            TrailingStopAuditRepository,
        )
        from iguanatrader.contexts.risk.trailing_stop_sweep import TrailingStopSweepService

        # Audit #6: protection-model selection. With native_bracket ON, the
        # broker holds a resting STP (+ optional LMT take-profit) submitted
        # atomically with the entry, so the daemon must NOT also run the
        # stop_hit/trailing sweeps — both would try to close the position and
        # double-sell. We therefore skip constructing + registering the sweeps
        # and leave the protective stop AT THE BROKER. With the flag OFF
        # (default) the sweeps are built + wired exactly as before.
        #
        # NOTE: native-bracket mode currently provides a FIXED protective stop
        # (+ optional take-profit) and does NOT perform daemon-side trailing
        # tightening — a documented follow-up.
        native_bracket = _native_bracket_enabled()
        stop_hit_sweep_service: Any | None = None
        trailing_stop_sweep_service: Any | None = None
        if native_bracket:
            log.info("trading.daemon.protection_model", model="broker_bracket")
        else:
            log.info("trading.daemon.protection_model", model="cron_sweep")
            # Shared audit repo — written by the trailing sweep (#38) and read
            # by the stop-hit sweep (#28). No explicit session (#29): it
            # resolves session_var at call time, so the SAME instance correctly
            # rides whichever per-tick sweep session is bound when each sweep
            # fires — the two sweeps run as separate cron jobs on separate
            # per-tick sessions now (see ``_sweep_unit_of_work`` below).
            trailing_audit_repo = TrailingStopAuditRepository()

            stop_hit_sweep_service = StopHitSweepService(
                # No session=... (#29): resolves the per-tick session the sweep
                # unit-of-work wrapper binds, not the long-lived ambient session.
                market_data_port=market_data_port,
                bus=bus,
                # #28: enforce the tightened trailing stop at close, not just
                # the proposal's original stop.
                trailing_audit_repo=trailing_audit_repo,
            )

            # #38: construct + register the trailing-stop sweep. It is inert by
            # construction until a tenant sets ``trail_trigger_pct`` (the
            # ``compute_trailing_stop`` short-circuit), so wiring it is safe;
            # before this it was never built, so trailing stops never ratcheted.
            trailing_stop_sweep_service = TrailingStopSweepService(
                # No session=... (#29): per-tick session via the sweep wrapper.
                audit_repo=trailing_audit_repo,
                risk_caps_provider=risk_service.load_caps,
                market_data_port=market_data_port,
            )

        # Slice ``dual-daemon-mode-toggle-and-reconcile``: per-daemon
        # lifecycle coordinator. Subscribes to DaemonDrainRequested +
        # DaemonReconcileRequested events filtered to this daemon's
        # mode. The repo + service are scoped to the session bound to
        # session_var above; the daemon-side bus delivery picks up the
        # contextvar so drain UPDATEs land on the correct session.
        trading_mode_repo = TradingModeRepository()
        equity_repo = EquitySnapshotRepository()
        lifecycle_service = DaemonLifecycleService(
            mode=mode,
            tenant_id=tenant_id,
            bus=bus,
            trading_service=trading_service,
            trading_mode_repo=trading_mode_repo,
            broker=broker,
            equity_repo=equity_repo,
            # Slice ``dual-daemon-followups`` Phase-2.5: lifecycle
            # service uses ``TradeRepository.list_open_for_tenant`` to
            # diff local open trades against broker positions during
            # reconcile. The same repo is already constructed for the
            # LLM-handler wiring above; we reuse it here.
            trade_repo=TradeRepository(),
        )
        lifecycle_service.register_subscriptions()

        orchestration_repo = OrchestrationRepository()
        orchestration_service = OrchestrationService(repository=orchestration_repo)

        # Audit #2/#27/#29: run each propose tick as its OWN committed unit of
        # work with publish-after-commit. This is REQUIRED now the bus delivers
        # per-event: it commits the proposal row before ``ProposalCreated`` is
        # published, so the risk subscriber (a fresh per-delivery session) sees
        # it. The session-only cron sweeps get the same treatment via
        # ``_sweep_unit_of_work`` below (per-tick fresh session + commit).
        from iguanatrader.shared.contextvars import run_in_session_scope

        async def _propose_unit_of_work(inner: Any) -> None:
            await run_in_session_scope(sessionmaker, bus, tenant_id, inner)

        # Audit #29 (cron side): run each session-only cron sweep tick
        # (trailing-stop, stop-hit, equity-snapshot, daemon-heartbeat) as its
        # OWN committed unit of work on a fresh per-tick session, instead of
        # sharing the long-lived ambient daemon session. This removes the
        # last concurrent-AsyncSession hazard: the 10s heartbeat and the
        # 1-min stop-hit sweep no longer touch one session at once. Same
        # wrapper shape as the propose unit of work, bound to the daemon's
        # single tenant (the sweeps that fan out across tenants — equity —
        # override the tenant context per row internally).
        async def _sweep_unit_of_work(inner: Any) -> None:
            await run_in_session_scope(sessionmaker, bus, tenant_id, inner)

        # Side-effect: registers cron JobSpecs on the scheduler (4 propose
        # routines + 5th market_data_sync + equity_snapshot_sweep +
        # stop_hit_sweep + daemon_heartbeat per-mode toggle gate wired
        # via the daemon_* params).
        await orchestration_service.bootstrap_routines(
            scheduler=scheduler,
            trading_service=trading_service,
            watchlist_symbols=watchlist_symbols,
            market_data_port=market_data_port,
            strategy_config_repo=strategy_config_repo,
            ingestion_service=ingestion_service,
            equity_snapshot_sweep_service=equity_snapshot_sweep_service,
            stop_hit_sweep_service=stop_hit_sweep_service,
            trailing_stop_sweep_service=trailing_stop_sweep_service,
            approval_service=approval_service,
            brief_refresh_service=brief_refresh_service,
            daemon_mode=mode,
            daemon_tenant_id=tenant_id,
            trading_mode_repo=trading_mode_repo,
            broker=broker,
            daemon_lifecycle_service=lifecycle_service,
            propose_unit_of_work=_propose_unit_of_work,
            sweep_unit_of_work=_sweep_unit_of_work,
        )

        # K1 (PR #103) + P1 (this slice) bus-bridge follow-ups close
        # the propose→risk→approve→execute chain end-to-end.
        log.info("trading.daemon.bus_subscriptions.complete")

        # Slice ``dual-daemon-mode-toggle-and-reconcile``: boot-time
        # reconcile with IBKR — runs once before the scheduler starts
        # so the first propose tick sees fresh broker state. Skip when
        # the operator has toggled this daemon off (don't pin a
        # disabled daemon's gateway with reconcile traffic on every
        # restart).
        try:
            boot_enabled = await trading_mode_repo.load_trading_enabled(tenant_id, mode)
        except Exception as exc:
            log.warning(
                "trading.daemon.boot_reconcile.gate_check_failed",
                error=str(exc),
            )
            boot_enabled = False
        if boot_enabled:
            try:
                await lifecycle_service.reconcile_with_ibkr()
            except Exception as exc:
                log.warning(
                    "trading.daemon.boot_reconcile.failed",
                    error=str(exc),
                )
        else:
            log.info(
                "trading.daemon.boot_reconcile.skipped_disabled",
                mode=mode,
                tenant_id=str(tenant_id),
            )

        await scheduler.start()
        log.info("trading.daemon.scheduler_started")

        log.info(
            "trading.daemon.ready",
            tenant_id=str(tenant_id),
            mode=mode,
            watchlist_count=len(watchlist_symbols),
        )

        # Telegram inbound — tap-to-approve/reject. Only started when a bot
        # token is configured; owner-gated (fail-closed) and routed through
        # the same command dispatcher as typed /approve, so a tap records a
        # granted decision → ProposalApproved → bracketed execution.
        from iguanatrader.contexts.approval.channels.telegram_poller import (
            TelegramCallbackPoller,
        )

        telegram_poller: TelegramCallbackPoller | None = None
        telegram_poller_task: asyncio.Task[None] | None = None
        _tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if _tg_token:
            telegram_poller = TelegramCallbackPoller(
                bot_token=_tg_token,
                tenant_id=tenant_id,
                service=approval_service,
                message_bus=bus,
                repository=approval_repository,
                session_factory=sessionmaker,
            )
            telegram_poller_task = asyncio.create_task(telegram_poller.run())
            log.info("trading.daemon.telegram_poller_started")

        await shutdown_event.wait()

        log.info("trading.daemon.shutdown.draining")
        if telegram_poller is not None:
            try:
                await telegram_poller.stop()
            except Exception as exc:
                log.warning("trading.daemon.telegram_poller.shutdown_failed", error=str(exc))
        if telegram_poller_task is not None:
            telegram_poller_task.cancel()
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


async def _build_broker(*, ib_client: IbAsyncIBClient, mode: str, tenant_id: UUID) -> IBKRAdapter:
    """Construct the production :class:`IBKRAdapter` with the supplied IB client.

    `IbAsyncIBClient` is structurally compatible with the `IBClient`
    Protocol (per slice T2 design D7), so we cast() to bypass mypy's
    nominal-typing check on the `client_factory` callable arg.

    ``tenant_id`` is the daemon's tenant: IBKR executions carry no tenant of
    their own, so the adapter stamps reconciled ``FillEvent``s with it. Without
    it fills were stamped with the zero UUID, the tenant-scoped order lookup
    never matched (``order_missing``) and the fill insert tripped the tenant
    guard.
    """
    from iguanatrader.contexts.trading.brokers.client_protocol import IBClient
    from iguanatrader.contexts.trading.brokers.ibkr_adapter import IBKRAdapter
    from iguanatrader.contexts.trading.brokers.ibkr_brokerage_model import (
        IBKRBrokerageModel,
    )

    brokerage = IBKRBrokerageModel.from_env(cast('Literal["paper", "live"]', mode))
    return IBKRAdapter(
        brokerage=brokerage,
        client_factory=lambda: cast("IBClient", ib_client),
        native_bracket=_native_bracket_enabled(),
        tenant_id=tenant_id,
    )


def _native_bracket_enabled() -> bool:
    """Audit #6: native IBKR bracket/OCO orders, behind a feature flag.

    ``IGUANATRADER_NATIVE_BRACKET`` truthy ∈ {1,true,yes,on} (case-insensitive),
    default OFF. When OFF the adapter submits naked orders + the daemon's
    stop_hit_sweep cron enforces protective stops — byte-identical to today.
    """
    return os.environ.get("IGUANATRADER_NATIVE_BRACKET", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
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
    from iguanatrader.shared.contextvars import with_session_context

    manager = StrategyManager()

    async def _resolve(strategy_config_id: UUID) -> StrategyPort:
        # Bind the resolver's read session for the duration of the lookup
        # ONLY, then restore the caller's session (audit #29 unit-of-work
        # fix). A bare ``session_var.set(session)`` here leaks the throwaway
        # read session into the caller's context: the subsequent
        # ``TradingService.propose`` would then ``session.add`` the proposal
        # row into this already-closed resolver session (never committed by
        # the per-tick ``run_in_session_scope``), so no proposal ever
        # persisted and the connection leaked.
        async with session_factory() as session, with_session_context(session):
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
