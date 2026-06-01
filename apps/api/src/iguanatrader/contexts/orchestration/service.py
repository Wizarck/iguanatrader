"""Orchestration service — slice O2 facade.

Facade orchestrates the per-routine pipeline:

1. Insert ``routine_runs`` row with ``status='running'``.
2. Collect facts (research_facts + open positions + equity snapshots).
3. Synthesize digest (LLM call gated by O1 budget — production wiring
   uses :class:`LLMClient` Protocol from R5; tests inject a fake).
4. Classify any cross-context events that fired during the window via
   :func:`classify_event`; tier-1 emits immediately, tier-2 accumulates
   into the digest, tier-3 audit-only.
5. Publish ``orchestration.<routine>.digest_published`` event for P1.
6. Update ``routine_runs`` to terminal status.

Idempotency on duplicate triggers via the
``uq_routine_runs_routine_name_scheduled_at_tenant_id`` unique index.
Budget gate via O1's :func:`check_budget` — :class:`BudgetStatus.BLOCK_100`
short-circuits to ``status='skipped_budget'``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from iguanatrader.contexts.orchestration.alert_filter import (
    AlertTier,
    Classification,
    classify_event,
)
from iguanatrader.contexts.orchestration.errors import (
    DuplicateRoutineTriggerError,
)
from iguanatrader.shared.time import now as utc_now

if TYPE_CHECKING:
    from iguanatrader.contexts.orchestration.repository import (
        OrchestrationRepository,
    )

logger = logging.getLogger(__name__)


RoutineName = Literal["premarket", "midday", "postmarket", "weekly_review"]


@dataclass(frozen=True, slots=True)
class RoutineOutcome:
    """Result returned from :meth:`OrchestrationService.run_routine`."""

    routine_name: RoutineName
    scheduled_at: datetime
    status: str
    duration_ms: int
    digest_payload: dict[str, object]
    tier_1_alerts: list[Classification]
    tier_2_alerts: list[Classification]


@dataclass(frozen=True, slots=True)
class RoutineWindow:
    """Window bounds + facts collected for a routine.

    Concrete routine implementations (e.g. ``premarket_window``) build
    this dataclass; the service consumes it during synthesis.
    """

    start_at: datetime
    end_at: datetime
    research_fact_count: int
    open_position_count: int
    pending_proposal_count: int


class OrchestrationService:
    """Facade for slice O2 routine execution."""

    def __init__(self, repository: OrchestrationRepository) -> None:
        self._repo = repository

    async def run_routine(
        self,
        *,
        routine_name: RoutineName,
        scheduled_at: datetime,
        events_during_window: list[tuple[str, dict[str, object]]] | None = None,
        synthesize_digest: bool = True,
        budget_blocked: bool = False,
    ) -> RoutineOutcome:
        """Execute one routine. Per-routine fact-collection + digest +
        alert classification.

        ``budget_blocked`` is a pre-computed boolean fed by the caller
        (typically an outer service that called O1's :func:`check_budget`);
        when True, the routine short-circuits to status='skipped_budget'
        with a deterministic-fallback digest. ``synthesize_digest=False``
        is used by tests + dry-runs.
        """
        started_at = utc_now()

        try:
            run_id = await self._repo.insert_routine_run(
                routine_name=routine_name,
                scheduled_at=scheduled_at,
                started_at=started_at,
                status="running",
            )
        except DuplicateRoutineTriggerError:
            logger.info(
                "orchestration.routine.duplicate_trigger",
                extra={
                    "routine_name": routine_name,
                    "scheduled_at": scheduled_at.isoformat(),
                },
            )
            return RoutineOutcome(
                routine_name=routine_name,
                scheduled_at=scheduled_at,
                status="skipped_duplicate",
                duration_ms=0,
                digest_payload={},
                tier_1_alerts=[],
                tier_2_alerts=[],
            )

        events = events_during_window or []
        classifications = [classify_event(event_name, payload) for event_name, payload in events]
        tier_1 = [c for c in classifications if c.tier is AlertTier.TIER_1]
        tier_2 = [c for c in classifications if c.tier is AlertTier.TIER_2]
        tier_3 = [c for c in classifications if c.tier is AlertTier.TIER_3]

        # Persist alert events.
        for cls in classifications:
            await self._repo.insert_alert_event(
                event_name=cls.event_name,
                tier=int(cls.tier),
                routing_decision=str(cls.routing),
                payload=cls.payload,
            )

        if budget_blocked:
            ended_at = utc_now()
            duration_ms = int((ended_at - started_at).total_seconds() * 1000)
            digest = self._fallback_digest(
                routine_name=routine_name,
                tier_1_alerts=tier_1,
                tier_2_alerts=tier_2,
                tier_3_alerts=tier_3,
            )
            await self._repo.update_routine_run(
                run_id=run_id,
                status="skipped_budget",
                ended_at=ended_at,
                duration_ms=duration_ms,
                digest_payload=digest,
            )
            return RoutineOutcome(
                routine_name=routine_name,
                scheduled_at=scheduled_at,
                status="skipped_budget",
                duration_ms=duration_ms,
                digest_payload=digest,
                tier_1_alerts=tier_1,
                tier_2_alerts=tier_2,
            )

        digest = self._build_digest(
            routine_name=routine_name,
            scheduled_at=scheduled_at,
            tier_1_alerts=tier_1,
            tier_2_alerts=tier_2,
            tier_3_alerts=tier_3,
            include_synthesis=synthesize_digest,
        )

        # Slice deployment-foundation §3.E.2 — render weekly-review PDF
        # alongside the markdown digest. Side-effect only (PDF path is
        # logged, not added to RoutineOutcome to avoid breaking the
        # frozen-dataclass shape callers depend on). Operator inspects
        # the PDF at data/weekly_reviews/<scheduled_at-date>.pdf.
        if routine_name == "weekly_review":
            self._render_weekly_review_pdf_side_effect(digest, scheduled_at)

        ended_at = utc_now()
        duration_ms = int((ended_at - started_at).total_seconds() * 1000)
        await self._repo.update_routine_run(
            run_id=run_id,
            status="success",
            ended_at=ended_at,
            duration_ms=duration_ms,
            digest_payload=digest,
        )

        logger.info(
            "orchestration.routine.completed",
            extra={
                "routine_name": routine_name,
                "duration_ms": duration_ms,
                "tier_1_count": len(tier_1),
                "tier_2_count": len(tier_2),
            },
        )

        return RoutineOutcome(
            routine_name=routine_name,
            scheduled_at=scheduled_at,
            status="success",
            duration_ms=duration_ms,
            digest_payload=digest,
            tier_1_alerts=tier_1,
            tier_2_alerts=tier_2,
        )

    # ------------------------------------------------------------------
    # Digest builders
    # ------------------------------------------------------------------

    @staticmethod
    def _build_digest(
        *,
        routine_name: RoutineName,
        scheduled_at: datetime,
        tier_1_alerts: list[Classification],
        tier_2_alerts: list[Classification],
        tier_3_alerts: list[Classification],
        include_synthesis: bool,
    ) -> dict[str, object]:
        """Compose the digest payload published on the bus.

        Real LLM synthesis is wired via the deployment-foundation slice
        (Anthropic SDK install + cost_meter wrap). MVP emits a
        deterministic structured digest.
        """
        return {
            "routine_name": routine_name,
            "scheduled_at_iso": scheduled_at.isoformat(),
            "title": _ROUTINE_TITLES[routine_name],
            "alert_summary": {
                "tier_1_count": len(tier_1_alerts),
                "tier_2_count": len(tier_2_alerts),
                "tier_3_count": len(tier_3_alerts),
            },
            "tier_1_events": [
                {"event_name": c.event_name, "payload": c.payload} for c in tier_1_alerts
            ],
            "tier_2_events": [
                {"event_name": c.event_name, "payload": c.payload} for c in tier_2_alerts
            ],
            "synthesis_present": include_synthesis,
            "synthesis_text": (
                _DETERMINISTIC_TEMPLATE[routine_name] if include_synthesis else None
            ),
        }

    async def bootstrap_routines(
        self,
        *,
        scheduler: Any,
        trading_service: Any,
        watchlist_symbols: list[str],
        market_data_port: Any | None = None,
        strategy_config_repo: Any | None = None,
        ingestion_service: Any | None = None,
        trailing_stop_sweep_service: Any | None = None,
        equity_snapshot_sweep_service: Any | None = None,
        stop_hit_sweep_service: Any | None = None,
        daemon_mode: str | None = None,
        daemon_tenant_id: Any | None = None,
        trading_mode_repo: Any | None = None,
        broker: Any | None = None,
        daemon_lifecycle_service: Any | None = None,
        timeframe: str = "1d",
        lookback_bars: int = 200,
        propose_unit_of_work: Callable[[Callable[[], Awaitable[None]]], Awaitable[None]]
        | None = None,
        sweep_unit_of_work: Callable[[Callable[[], Awaitable[None]]], Awaitable[None]]
        | None = None,
    ) -> None:
        """Register cron triggers for the 4 propose routines + market_data_sync.

        ``propose_unit_of_work`` (audit #2/#27/#29): when supplied, each propose
        tick runs THROUGH it — the daemon passes a wrapper that opens a fresh
        per-tick session + commits + publishes its events only after the commit
        (``run_in_session_scope``). This is REQUIRED once the bus delivers in
        per-delivery sessions: without it the propose tick would publish
        ``ProposalCreated`` before the proposal row committed, and the risk
        subscriber (reading in its own session) would not see it. ``None``
        (older/test setups) runs the tick directly on the ambient session.

        ``sweep_unit_of_work`` (audit #29, cron side): same wrapper shape for the
        session-only cron sweeps (trailing-stop, stop-hit, equity-snapshot,
        daemon-heartbeat). Before this each sweep tick ran on the SHARED
        long-lived daemon session, so two sweeps firing close together (e.g. the
        10s heartbeat overlapping the 1-min stop-hit sweep) used one
        ``AsyncSession`` concurrently — the #29 isolation hazard. With the
        wrapper each tick opens its own fresh session + commits at the boundary.
        ``None`` keeps the ambient-session behaviour for older/test setups.

        Slice T4-followup-market-data §2.11: replaces the T4
        ``_placeholder`` no-op with a real per-symbol propose loop and
        adds a 5th routine ``market_data_sync`` (daily 06:00 UTC) that
        invokes the IBKR ingestion service.

        Backwards-compat: ``market_data_port`` / ``strategy_config_repo``
        / ``ingestion_service`` are Optional. If not supplied (older
        test setups), the routines fall back to the original no-op
        ``_placeholder`` and the ``market_data_sync`` routine is
        skipped.
        """
        from iguanatrader.contexts.orchestration.scheduler import JobSpec

        cron_kwargs_by_routine: dict[str, dict[str, object]] = {
            "premarket": {"hour": 8, "minute": 0, "day_of_week": "mon-fri"},
            "midday": {"hour": 12, "minute": 30, "day_of_week": "mon-fri"},
            "postmarket": {"hour": 16, "minute": 30, "day_of_week": "mon-fri"},
            "weekly_review": {"hour": 17, "minute": 0, "day_of_week": "fri"},
        }

        wire_propose_loops = market_data_port is not None and strategy_config_repo is not None
        # Local non-None aliases (mypy can't track the wire_propose_loops guard
        # into the nested closure; explicit captures make the union narrowing
        # visible inside ``_propose``).
        md_port: Any = market_data_port
        sc_repo: Any = strategy_config_repo

        async def _placeholder() -> None:
            """Fallback no-op when market-data wiring is absent (test setups)."""
            return None

        # Slice ``dual-daemon-mode-toggle-and-reconcile``: each propose
        # tick reads the per-(tenant, mode) ``trading_enabled`` flag at
        # the top and short-circuits when the operator has toggled the
        # daemon off. ``trading_mode_gate_active`` is True only when ALL
        # daemon-side params are wired — older test setups that don't
        # pass them keep the unfiltered behaviour.
        trading_mode_gate_active = (
            daemon_mode is not None
            and daemon_tenant_id is not None
            and trading_mode_repo is not None
        )
        gated_mode: str = daemon_mode if daemon_mode is not None else ""
        gated_tenant_id: Any = daemon_tenant_id
        gated_mode_repo: Any = trading_mode_repo

        def _make_propose_fn(routine_name: str) -> Callable[[], Awaitable[None]]:
            async def _propose() -> None:
                if trading_mode_gate_active:
                    try:
                        enabled = await gated_mode_repo.load_trading_enabled(
                            gated_tenant_id, gated_mode
                        )
                    except Exception as exc:
                        logger.warning(
                            "orchestration.propose.gate_check_failed",
                            extra={
                                "routine": routine_name,
                                "mode": gated_mode,
                                "error": str(exc),
                            },
                        )
                        return
                    if not enabled:
                        logger.info(
                            "orchestration.propose.skipped_disabled",
                            extra={
                                "routine": routine_name,
                                "mode": gated_mode,
                                "tenant_id": str(gated_tenant_id),
                            },
                        )
                        return

                for symbol in watchlist_symbols:
                    try:
                        configs = await sc_repo.list_enabled_for_symbol(symbol)
                        if not configs:
                            continue
                        bars = await md_port.get_bars(
                            symbol=symbol,
                            timeframe=timeframe,
                            lookback_bars=lookback_bars,
                        )
                        from iguanatrader.contexts.trading.ports import (
                            StrategyConfigSnapshot,
                        )

                        for config in configs:
                            snapshot = StrategyConfigSnapshot(
                                id=config.id,
                                tenant_id=config.tenant_id,
                                strategy_kind=config.strategy_kind,
                                symbol=config.symbol,
                                params=dict(config.params),
                                enabled=config.enabled,
                                version=config.version,
                            )
                            await trading_service.propose(
                                symbol=symbol,
                                strategy_config_id=config.id,
                                bars=bars,
                                config=snapshot,
                            )
                    except Exception as exc:
                        logger.warning(
                            "orchestration.routine.symbol_failed",
                            extra={
                                "symbol": symbol,
                                "routine": routine_name,
                                "error": str(exc),
                            },
                        )
                        continue

            return _propose

        def _wrap_in_uow(
            inner: Callable[[], Awaitable[None]],
            uow: Callable[[Callable[[], Awaitable[None]]], Awaitable[None]] | None,
        ) -> Callable[[], Awaitable[None]]:
            """Run ``inner`` through the per-tick unit of work ``uow``, when given.

            ``uow`` (audit #2/#27/#29) opens a FRESH per-tick session, binds the
            contextvars, commits at the boundary, and publishes any events the
            tick produced only AFTER the commit (publish-after-commit). ``None``
            (older / test setups) runs ``inner`` directly on the ambient
            session. Used for both the propose ticks (``propose_unit_of_work``)
            and the session-only cron sweeps (``sweep_unit_of_work``) so neither
            shares the long-lived daemon session any more.
            """
            if uow is None:
                return inner

            async def _run() -> None:
                await uow(inner)

            return _run

        for routine_name, cron_kwargs in cron_kwargs_by_routine.items():
            fn = (
                _wrap_in_uow(_make_propose_fn(routine_name), propose_unit_of_work)
                if wire_propose_loops
                else _placeholder
            )
            spec = JobSpec(
                name=routine_name,
                fn=fn,
                cron_kwargs=cron_kwargs,
            )
            scheduler.add_job(spec)

        if ingestion_service is not None:

            async def _ingest_market_data() -> None:
                from iguanatrader.contexts.trading.market_data import (
                    MarketDataRateLimitedError,
                )

                try:
                    result = await ingestion_service.sync(
                        symbols=watchlist_symbols,
                        timeframe=timeframe,
                        lookback_bars=lookback_bars,
                        invoked_by="daemon-cron",
                    )
                    logger.info(
                        "orchestration.market_data_sync.complete",
                        extra={
                            "successes": len(result.successes),
                            "failures": len(result.failures),
                            "bars_written": result.bars_written,
                        },
                    )
                except MarketDataRateLimitedError as exc:
                    logger.warning(
                        "orchestration.market_data_sync.rate_limited",
                        extra={"error": str(exc)},
                    )
                except Exception as exc:
                    logger.error(
                        "orchestration.market_data_sync.failed",
                        extra={"error": str(exc)},
                    )

            sync_spec = JobSpec(
                name="market_data_sync",
                fn=_ingest_market_data,
                cron_kwargs={"hour": 6, "minute": 0, "day_of_week": "mon-fri"},
            )
            scheduler.add_job(sync_spec)

        # Slice orchestration-trailing-stops-cron: 6th job sweeps open
        # trades every 15 min during US market hours (9-16 UTC matches
        # the existing market-hours convention; the daemon's clock is
        # UTC). The sweep service short-circuits internally when
        # ``RiskCaps.trail_trigger_pct is None`` so registration is
        # unconditional — gating happens via the cap, not via the
        # bootstrap. Backwards-compat: when the service is not wired
        # (older test setups), the cron is skipped.
        if trailing_stop_sweep_service is not None:
            sweep_service: Any = trailing_stop_sweep_service

            async def _sweep_trailing_stops() -> None:
                try:
                    result = await sweep_service.sweep()
                    logger.info(
                        "orchestration.trailing_stops_sweep.complete",
                        extra={
                            "trades_evaluated": result.trades_evaluated,
                            "trades_trailed": result.trades_trailed,
                            "trades_no_update": result.trades_no_update,
                            "trades_trigger_not_reached": result.trades_trigger_not_reached,
                            "trades_skipped_no_bars": result.trades_skipped_no_bars,
                            "duration_ms": result.duration_ms,
                        },
                    )
                except Exception as exc:
                    logger.error(
                        "orchestration.trailing_stops_sweep.failed",
                        extra={"error": str(exc), "type": type(exc).__name__},
                    )

            sweep_spec = JobSpec(
                name="trailing_stops_sweep",
                fn=_wrap_in_uow(_sweep_trailing_stops, sweep_unit_of_work),
                cron_kwargs={
                    "hour": "9-16",
                    "minute": "*/15",
                    "day_of_week": "mon-fri",
                },
            )
            scheduler.add_job(sweep_spec)

        # Slice exit-classification-stop-hit-sweep: 8th job watches
        # every open trade for stop-price + target-price breaches every
        # minute during US market hours and emits
        # CloseTradeRequested when a level is hit. Closes the auto-
        # close loop that K1's stoploss_guard depends on. Skipped when
        # the service is not wired (test setups + scheduler-only mode).
        if stop_hit_sweep_service is not None:
            stop_hit_service: Any = stop_hit_sweep_service

            async def _sweep_stop_hits() -> None:
                try:
                    result = await stop_hit_service.sweep()
                    logger.info(
                        "orchestration.stop_hit_sweep.complete",
                        extra={
                            "trades_evaluated": result.trades_evaluated,
                            "stop_hits_emitted": result.stop_hits_emitted,
                            "target_hits_emitted": result.target_hits_emitted,
                            "trades_skipped_no_bars": result.trades_skipped_no_bars,
                            "duration_ms": result.duration_ms,
                        },
                    )
                except Exception as exc:
                    logger.error(
                        "orchestration.stop_hit_sweep.failed",
                        extra={"error": str(exc), "type": type(exc).__name__},
                    )

            stop_hit_spec = JobSpec(
                name="stop_hit_sweep",
                fn=_wrap_in_uow(_sweep_stop_hits, sweep_unit_of_work),
                cron_kwargs={
                    "hour": "9-16",
                    "minute": "*",  # every minute during US market hours
                    "day_of_week": "mon-fri",
                },
            )
            scheduler.add_job(stop_hit_spec)

        # Slice equity-snapshot-daemon: 7th job captures account equity
        # for every tenant every 15 min during US market hours. Drives
        # the rolling drawdown window K1's max-drawdown protection reads
        # from. Backwards-compat: skipped when the service is not wired
        # (older test setups).
        if equity_snapshot_sweep_service is not None:
            equity_service: Any = equity_snapshot_sweep_service

            async def _sweep_equity_snapshots() -> None:
                try:
                    result = await equity_service.sweep()
                    logger.info(
                        "orchestration.equity_snapshot_sweep.complete",
                        extra={
                            "tenants_evaluated": result.tenants_evaluated,
                            "snapshots_persisted": result.snapshots_persisted,
                            "broker_errors": result.broker_errors,
                            "duration_ms": result.duration_ms,
                        },
                    )
                except Exception as exc:
                    logger.error(
                        "orchestration.equity_snapshot_sweep.failed",
                        extra={"error": str(exc), "type": type(exc).__name__},
                    )

            equity_spec = JobSpec(
                name="equity_snapshot_sweep",
                fn=_wrap_in_uow(_sweep_equity_snapshots, sweep_unit_of_work),
                cron_kwargs={
                    "hour": "9-16",
                    "minute": "*/15",
                    "day_of_week": "mon-fri",
                },
            )
            scheduler.add_job(equity_spec)

        # Slice ``dual-daemon-mode-toggle-and-reconcile``: 9th job writes
        # a heartbeat row every 10 seconds so ``GET /api/v1/status`` can
        # render ``ib_connected`` + ``last_heartbeat_at`` for the chip.
        # Fires unconditionally (even when ``trading_enabled=false``) so
        # the operator can see "the daemon process is alive and just
        # idle" vs "the daemon is dead." Skipped if daemon-side params
        # are not wired (older test setups).
        daemon_heartbeat_wired = (
            daemon_mode is not None
            and daemon_tenant_id is not None
            and trading_mode_repo is not None
            and broker is not None
        )
        if daemon_heartbeat_wired:
            hb_mode: str = daemon_mode if daemon_mode is not None else ""
            hb_tenant_id: Any = daemon_tenant_id
            hb_repo: Any = trading_mode_repo
            hb_broker: Any = broker
            hb_lifecycle: Any = daemon_lifecycle_service

            async def _heartbeat() -> None:
                try:
                    state = getattr(hb_broker, "state", None)
                    state_value = getattr(state, "value", None) if state is not None else None
                    ib_connected = state_value == "connected"
                    await hb_repo.write_heartbeat(
                        tenant_id=hb_tenant_id,
                        mode=hb_mode,
                        ib_connected=ib_connected,
                    )
                except Exception as exc:
                    logger.warning(
                        "orchestration.daemon_heartbeat.failed",
                        extra={
                            "mode": hb_mode,
                            "error": str(exc),
                            "type": type(exc).__name__,
                        },
                    )

                # Phase 3.5 cross-process poll — detect API-side toggle
                # / reconcile requests + run drain or reconcile when
                # newer than the in-memory watermarks. Best-effort: a
                # failure here logs but does not break the heartbeat
                # write loop above.
                if hb_lifecycle is not None:
                    try:
                        await hb_lifecycle.poll_for_state_changes()
                    except Exception as exc:
                        logger.warning(
                            "orchestration.daemon_heartbeat.poll_failed",
                            extra={
                                "mode": hb_mode,
                                "error": str(exc),
                                "type": type(exc).__name__,
                            },
                        )

            heartbeat_spec = JobSpec(
                name="daemon_heartbeat",
                fn=_wrap_in_uow(_heartbeat, sweep_unit_of_work),
                cron_kwargs={"second": "*/10"},
            )
            scheduler.add_job(heartbeat_spec)

        logger.info(
            "orchestration.routines.bootstrapped",
            extra={
                "routine_count": (
                    len(cron_kwargs_by_routine)
                    + (1 if ingestion_service is not None else 0)
                    + (1 if trailing_stop_sweep_service is not None else 0)
                    + (1 if equity_snapshot_sweep_service is not None else 0)
                    + (1 if stop_hit_sweep_service is not None else 0)
                    + (1 if daemon_heartbeat_wired else 0)
                ),
                "watchlist_count": len(watchlist_symbols),
                "propose_loops_wired": wire_propose_loops,
                "propose_gate_active": trading_mode_gate_active,
                "market_data_sync_wired": ingestion_service is not None,
                "trailing_stops_sweep_wired": trailing_stop_sweep_service is not None,
                "equity_snapshot_sweep_wired": equity_snapshot_sweep_service is not None,
                "stop_hit_sweep_wired": stop_hit_sweep_service is not None,
                "daemon_heartbeat_wired": daemon_heartbeat_wired,
            },
        )

    @staticmethod
    def _render_weekly_review_pdf_side_effect(
        digest: dict[str, object],
        scheduled_at: datetime,
    ) -> None:
        """Render the weekly-review PDF and write to ``data/weekly_reviews/``.

        Slice deployment-foundation §3.E.2. Wraps the renderer in a
        broad try/except: a missing reportlab dep MUST NOT break the
        routine — the markdown digest is the primary deliverable, the
        PDF is supplementary.
        """
        try:
            from pathlib import Path

            from iguanatrader.contexts.orchestration.weekly_review_pdf import (
                render_weekly_review_pdf,
            )

            pdf_dir = Path("data/weekly_reviews")
            pdf_dir.mkdir(parents=True, exist_ok=True)
            pdf_path = pdf_dir / f"{scheduled_at.date().isoformat()}.pdf"
            pdf_bytes = render_weekly_review_pdf(digest, review_date=scheduled_at.date())
            pdf_path.write_bytes(pdf_bytes)
            logger.info(
                "orchestration.weekly_review.pdf_rendered",
                extra={"path": str(pdf_path), "size_bytes": len(pdf_bytes)},
            )
        except Exception as exc:
            logger.warning(
                "orchestration.weekly_review.pdf_failed",
                extra={"error": str(exc), "type": type(exc).__name__},
            )

    @staticmethod
    def _fallback_digest(
        *,
        routine_name: RoutineName,
        tier_1_alerts: list[Classification],
        tier_2_alerts: list[Classification],
        tier_3_alerts: list[Classification],
    ) -> dict[str, object]:
        return {
            "routine_name": routine_name,
            "title": _ROUTINE_TITLES[routine_name],
            "fallback_reason": "monthly_llm_budget_blocked",
            "alert_summary": {
                "tier_1_count": len(tier_1_alerts),
                "tier_2_count": len(tier_2_alerts),
                "tier_3_count": len(tier_3_alerts),
            },
            "tier_1_events": [
                {"event_name": c.event_name, "payload": c.payload} for c in tier_1_alerts
            ],
            "synthesis_present": False,
        }


# ----------------------------------------------------------------------
# Routine-specific titles + deterministic templates
# ----------------------------------------------------------------------


_ROUTINE_TITLES: dict[str, str] = {
    "premarket": "Pre-market briefing",
    "midday": "Midday pulse",
    "postmarket": "Post-market summary",
    "weekly_review": "Weekly review",
}

_DETERMINISTIC_TEMPLATE: dict[str, str] = {
    "premarket": (
        "Pre-market briefing: review overnight news, earnings calendar, "
        "and tier-1 alerts before the open."
    ),
    "midday": "Midday pulse: open positions + risk-engine state.",
    "postmarket": "Post-market summary: P&L + watchlist refresh for tomorrow.",
    "weekly_review": "Weekly review: equity curve + trade narrative + lessons + outlook.",
}


__all__ = [
    "OrchestrationService",
    "RoutineName",
    "RoutineOutcome",
    "RoutineWindow",
]
