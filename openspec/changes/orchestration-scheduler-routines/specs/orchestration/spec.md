## ADDED Requirements

### Requirement: Scheduler runs 4 ET-aware cron jobs via APScheduler with `SQLAlchemyJobStore`

The system SHALL provide `iguanatrader.contexts.orchestration.scheduler::create_scheduler(engine)` returning an `apscheduler.schedulers.asyncio.AsyncIOScheduler` configured with a `SQLAlchemyJobStore` (NOT `MemoryJobStore` — long-uptime memory leak prevention), `AsyncIOExecutor`, `coalesce=True`, `max_instances=1`, `misfire_grace_time=300`, and `timezone=zoneinfo.ZoneInfo("America/New_York")`. Four cron jobs SHALL be registered at app startup: `premarket` (`day_of_week="mon-fri"`, `hour=6`, `minute=30`), `midday` (`day_of_week="mon-fri"`, `hour=12`, `minute=30`), `postmarket` (`day_of_week="mon-fri"`, `hour=16`, `minute=30`), `weekly_review` (`day_of_week="sun"`, `hour=18`, `minute=0`). All times are interpreted in `America/New_York` with DST handled by `zoneinfo`.

#### Scenario: All 4 cron jobs registered at app startup with ET timezone

- **WHEN** the app starts and `OrchestrationService.start(message_bus, scheduler)` is invoked
- **THEN** the scheduler reports 4 active jobs (`premarket`, `midday`, `postmarket`, `weekly_review`)
- **AND** each job's `next_run_time` is in `America/New_York` timezone
- **AND** the `apscheduler_jobs` table is auto-created by APScheduler (out-of-band of our Alembic migrations)

#### Scenario: DST spring-forward — cron fires once per day, not zero or twice

- **GIVEN** `freezegun.freeze_time` walks across 2026-03-08 (US spring-forward at 02:00 → 03:00 ET)
- **WHEN** the simulated day completes
- **THEN** the `premarket` cron has fired exactly once (at 06:30 ET on 2026-03-08)
- **AND** the `midday` cron has fired exactly once (at 12:30 ET)
- **AND** the `postmarket` cron has fired exactly once (at 16:30 ET)
- **AND** no cron fires inside the skipped 02:00-03:00 ET window

#### Scenario: DST fall-back — cron fires once per day, not zero or twice

- **GIVEN** `freezegun.freeze_time` walks across 2026-11-01 (US fall-back at 02:00 → 01:00 ET)
- **WHEN** the simulated day completes
- **THEN** each cron fires exactly once on 2026-11-01 (no double-firing despite the duplicated 01:00-02:00 hour)
- **AND** the `weekly_review` cron fires exactly once at 18:00 ET (post-fall-back)

### Requirement: Each routine executes as a LangGraph `StateGraph` workflow

The system SHALL implement each of the 4 routines as a `langgraph.StateGraph[RoutineState]` compiled with a `MemorySaver()` checkpointer. Each graph SHALL define exactly 4 nodes wired sequentially: `collect_facts → synthesize_brief → filter_alerts → publish_digest`. The `RoutineState` SHALL be a Pydantic v2 model with fields `tenant_id`, `routine_run_id`, `scheduled_at`, `routine_name`, `facts`, `digest`, `alerts_emitted`, `errors`. Each node SHALL be a pure async function consuming and returning `RoutineState`.

#### Scenario: Premarket graph executes 4 nodes sequentially

- **GIVEN** mocked R1/R2/R3 repositories returning canned `Fact` lists
- **AND** a `_FakeLLMClient` returning canned `LLMResponse` for the synthesize call
- **WHEN** `build_premarket_graph().ainvoke({"tenant_id": tenant_a, "routine_run_id": run_id, "scheduled_at": ts, "routine_name": "premarket"})` is invoked
- **THEN** all 4 nodes execute in order (`collect_facts → synthesize_brief → filter_alerts → publish_digest`)
- **AND** the final `RoutineState.digest` is non-None
- **AND** the LangGraph emits `node_started` / `node_finished` events for each node
- **AND** the MessageBus event `orchestration.premarket.digest_published` is emitted

#### Scenario: LangGraph node failure routes to error handler

- **GIVEN** the `synthesize_brief` node raises `RuntimeError("LLM SDK timeout")` on first attempt
- **WHEN** the graph is invoked
- **THEN** the routine_runs row updates to `status='error'`, `error_message='LLM SDK timeout'`
- **AND** the next node (`filter_alerts`) does NOT execute
- **AND** a tier-1 alert `orchestration.routine.error` is emitted

### Requirement: Tier-1/2/3 alert filter classifies events synchronously with publication

The system SHALL provide `iguanatrader.contexts.orchestration.alert_filter::AlertFilter` with `subscribe_all(message_bus)` registering callbacks for the canonical event names defined in `tier1_alerts.py::TIER_1_RULES`. The `classify_event(event_name, payload) -> AlertTier` method SHALL be deterministic, rules-based, and complete in <1ms (no LLM call). Tier-1 events SHALL be persisted to `alert_events` AND published via `MessageBus("approval.alert.tier_1", ...)` synchronously with the source event arrival (NFR-P3 = p99 < 60s end-to-end). Tier-2 events SHALL be added to a per-tenant in-memory `deque[AlertEvent]` queue drained by the next cron-fired routine. Tier-3 events SHALL be persisted to `audit_log` only (no MessageBus publish).

#### Scenario: Kill switch trip → tier-1 alert emitted within 60s

- **GIVEN** the AlertFilter has subscribed at app startup
- **WHEN** a `risk.kill_switch.tripped` event is published to the MessageBus at T0
- **THEN** at T0 + <1s, an `alert_events` row is persisted with `tier=1`, `event_name='risk.kill_switch.tripped'`, `routing_decision={"emitted_to_channels": ["telegram", "hermes"]}`
- **AND** the MessageBus event `approval.alert.tier_1` is published with the original payload + source_event_name
- **AND** P1's Telegram channel subscriber processes the event and posts to the user's chat within 60s (NFR-P3 p99)

#### Scenario: Insider buy 5% → tier-3 (no rule match → audit only)

- **GIVEN** `tier1_alerts.py::TIER_1_RULES["research.insider.buy_pct"]` has predicate `lambda p: p.get("pct", 0) >= 10`
- **WHEN** `research.insider.buy_pct` is published with payload `{"pct": 5, "symbol": "AAPL"}`
- **THEN** the rule predicate evaluates False
- **AND** the event falls through to tier-3 (no rule match)
- **AND** the event is persisted to `audit_log` only (no `alert_events` row, no MessageBus tier-1 publish)

#### Scenario: Tier-2 events accumulate across routine boundaries

- **GIVEN** premarket has just completed
- **WHEN** between premarket and midday cron fires, 3 tier-2 events arrive
- **THEN** all 3 are appended to the per-tenant tier-2 deque + persisted to `alert_events` with `tier=2`
- **AND** when the midday cron fires, `filter_alerts` node calls `AlertFilter.drain_tier2_queue(tenant_id)` and receives all 3 events
- **AND** after `drain_tier2_queue`, the queue is empty

### Requirement: `routine_runs` persists every cron execution + enforces 5-min SLA

The system SHALL define `routine_runs` (per migration `0007_orchestration_tables.py`) with columns `id`, `tenant_id`, `routine_name`, `scheduled_at`, `started_at`, `ended_at`, `status`, `duration_ms`, `cost_usd`, `digest_payload JSONB`, `error_message`, `created_at`. The `status` column SHALL be one of `running | success | timeout | error | skipped_budget | skipped_duplicate`. The table SHALL be "mutable-then-frozen" — exactly one UPDATE allowed transitioning `status='running' → status IN terminal states`; any other UPDATE raises `AppendOnlyViolationError`. The `OrchestrationService.run_routine(name, scheduled_at, tenant_id)` SHALL wrap the LangGraph invocation in `asyncio.wait_for(timeout=300)`; on timeout, `status='timeout'` is recorded AND a tier-1 alert `orchestration.routine.timeout` is emitted. NFR-P3 (5min p95 routine SLA) SHALL be measured from `routine_runs.started_at` to `ended_at`.

#### Scenario: Successful routine — status transitions running → success

- **GIVEN** a fresh routine_runs row inserted at routine entry with `status='running', started_at=T0`
- **WHEN** the LangGraph completes successfully at T0+45s
- **THEN** the row updates to `status='success', ended_at=T0+45s, duration_ms=45000, cost_usd=0.012, digest_payload={...}`
- **AND** the `append_only_listener` accepts the UPDATE (legal `running → success` transition)
- **AND** subsequent UPDATE attempts on the same row raise `AppendOnlyViolationError`

#### Scenario: Routine exceeds 5min SLA — status='timeout' + tier-1 alert

- **GIVEN** the LangGraph invocation hangs (mocked LLM call sleeps forever)
- **WHEN** `asyncio.wait_for(timeout=300)` fires at T0+300s
- **THEN** the routine_runs row updates to `status='timeout', ended_at=T0+300s, duration_ms=300000, error_message='exceeded_5min_sla'`
- **AND** a tier-1 alert `orchestration.routine.timeout` is emitted with `{routine_name, scheduled_at, duration_ms=300000, last_node}`
- **AND** the next scheduled cron fire of the same routine proceeds normally

#### Scenario: Bootstrap janitor cleans orphan running rows

- **GIVEN** a previous process crashed mid-routine, leaving `routine_runs(status='running', started_at=T-15min)` orphaned
- **WHEN** the new process boots and `OrchestrationService.start()` runs `clean_orphan_runs(threshold_minutes=10)`
- **THEN** the orphan row updates to `status='timeout', ended_at=now, error_message='process_crashed_during_routine'`
- **AND** a tier-2 alert is emitted (NOT tier-1 — operational, not user-critical) so the operator sees the cleanup in the next routine digest

### Requirement: `alert_events` persists every classified event with tier + routing decision

The system SHALL define `alert_events` (per migration `0007_orchestration_tables.py`) with columns `id`, `tenant_id`, `event_name`, `tier` (CHECK IN (1, 2, 3)), `routing_decision JSONB`, `payload JSONB`, `correlation_id`, `source_event_id`, `source_event_name`, `created_at`. The table SHALL be append-only (registered with slice-3 `append_only_listener`). The `routing_decision` JSONB SHALL be a structured dict with documented keys (`emitted_to_channels: list[str]`, `deferred_to_digest: bool`, `audit_only: bool`, `suppressed_reason: str | None`). The SSE endpoint `GET /api/v1/stream/alerts` SHALL stream rows to authenticated clients, filtered by tenant + tier query param.

#### Scenario: Tier-1 row records full routing decision

- **WHEN** a tier-1 event is classified and emitted to channels
- **THEN** the `alert_events` row is persisted with `tier=1`, `routing_decision={"emitted_to_channels": ["telegram", "hermes"], "deferred_to_digest": false, "audit_only": false, "suppressed_reason": null}`
- **AND** the row is append-only — UPDATE/DELETE attempts raise `AppendOnlyViolationError`

#### Scenario: SSE endpoint streams tier-1 events with tenant isolation

- **GIVEN** authenticated client A subscribed to `/api/v1/stream/alerts?tier=1`
- **AND** authenticated client B subscribed to the same endpoint
- **WHEN** a tier-1 event is published for tenant A
- **THEN** client A receives the SSE event within <500ms
- **AND** client B does NOT receive the event (cross-tenant isolation per NFR-SC1)

### Requirement: LLM cost budget gating runs at routine entry

The system SHALL provide `OrchestrationService.run_routine(name, scheduled_at, tenant_id)` invoking `iguanatrader.contexts.observability.budget::check_budget(tenant_id)` BEFORE instantiating the LangGraph workflow. On `BLOCK_100`, the routine SHALL skip the LangGraph entirely, persist `routine_runs` with `status='skipped_budget'`, build a deterministic fallback digest (raw facts as bullet points, no LLM call), publish the digest payload, and emit a tier-1 alert `observability.budget.block_100_routine_skipped`. On `WARN_80`, the routine SHALL proceed; the `route_llm()` call inside `synthesize_brief` will auto-downgrade per O1 D4. The slice SHALL also extend `cost_meter` to populate `api_cost_events.routine_run_id` from a new `routine_run_id_var` contextvar set at routine entry.

#### Scenario: BLOCK_100 at routine entry — skip LangGraph + emit fallback

- **GIVEN** `tenants.feature_flags["llm_budget_usd"] = 50.00`
- **AND** current month spend is 50.00 (100%)
- **WHEN** the premarket cron fires at 06:30 ET and `run_routine("premarket", ts, tenant_a)` is invoked
- **THEN** `check_budget(tenant_a)` returns `BudgetState(status=BLOCK_100, ...)`
- **AND** the LangGraph workflow is NOT instantiated (no LLM call attempted)
- **AND** `routine_runs` row persists with `status='skipped_budget', cost_usd=0, digest_payload={"fallback": true, "reason": "budget_block_100", "deterministic_summary": "<bullets>"}`
- **AND** a tier-1 alert `observability.budget.block_100_routine_skipped` is emitted

#### Scenario: Routine LLM call populates `api_cost_events.routine_run_id`

- **GIVEN** the premarket routine is running with `routine_run_id_var` set to UUID `r1`
- **WHEN** `synthesize_brief` calls the LLM SDK wrapped in `@cost_meter("anthropic", "claude-3-5-haiku")`
- **THEN** the resulting `api_cost_events` row has `routine_run_id=r1` (FK populated for the first time — slice O1 had this column NULL)
- **AND** at routine exit, `routine_runs.cost_usd = SUM(api_cost_events.cost_usd WHERE routine_run_id=r1)`

### Requirement: Idempotent triggers via UNIQUE constraint — duplicate fail-fast

The system SHALL define a UNIQUE constraint `uq_routine_runs_routine_name_scheduled_at` on `(routine_name, scheduled_at)` columns of `routine_runs`. When a duplicate INSERT fails with `IntegrityError` (e.g., scheduler restart re-fires a missed cron, or manual `run_routine_now` collides with a scheduled fire), the service SHALL catch the error, log `orchestration.routine.duplicate_trigger` at WARNING level, and insert a `routine_runs` row at `scheduled_at + 1ms` with `status='skipped_duplicate'` to preserve audit trail visibility. The original (winning) routine SHALL continue unaffected.

#### Scenario: Manual trigger collides with scheduled cron — loser logs skipped_duplicate

- **GIVEN** the premarket cron has just inserted `routine_runs(routine_name='premarket', scheduled_at=T)` and is executing
- **WHEN** an operator invokes `service.run_routine_now('premarket', tenant_a)` at T+10ms with the same effective `scheduled_at=T`
- **THEN** the manual trigger's INSERT raises `IntegrityError`
- **AND** the service catches the error and inserts `routine_runs(routine_name='premarket', scheduled_at=T+1ms, status='skipped_duplicate', error_message='duplicate_trigger_collision')`
- **AND** the original cron-fired routine completes unaffected

#### Scenario: Scheduler restart re-fires missed cron — coalesce protects

- **GIVEN** APScheduler is configured with `coalesce=True, max_instances=1`
- **WHEN** the process restarts after a 90-min downtime that crossed 2 scheduled premarket fires
- **THEN** APScheduler coalesces the missed fires into 1 catch-up run
- **AND** the catch-up run inserts `routine_runs` normally (no IntegrityError, no skipped_duplicate)

### Requirement: Weekly PDF report generated via `reportlab` and emitted as channel attachment

The system SHALL provide `iguanatrader.contexts.orchestration.report_pdf::build_weekly_review_pdf(state) -> bytes` returning a multi-page PDF assembled with `reportlab.platypus`. The PDF SHALL contain 7 sections: (1) title page, (2) equity curve (matplotlib PNG embed), (3) trade table, (4) per-strategy breakdown, (5) cost breakdown per LangGraph node, (6) lessons section (LLM-extracted), (7) outlook section (next-week earnings + macro). The weekly_review routine SHALL emit `MessageBus("orchestration.weekly_review.pdf_ready", {tenant_id, pdf_bytes, filename: "weekly-review-{iso_date}.pdf"})`. P1 channels SHALL consume this event: Telegram uploads as document attachment; Hermes saves to filesystem and posts the file link.

#### Scenario: Weekly review fires Sunday 18:00 ET — PDF generated and emitted

- **GIVEN** the weekly_review cron fires on Sunday 2026-05-03 18:00 ET
- **WHEN** the routine completes successfully
- **THEN** `MessageBus("orchestration.weekly_review.pdf_ready", ...)` is emitted with non-empty `pdf_bytes`
- **AND** the bytes start with the PDF magic header (`%PDF-`)
- **AND** all 7 sections are present in the PDF (verified via `pdfplumber` text extraction in test)
- **AND** `routine_runs.digest_payload` includes a reference to the PDF (`{"pdf_filename": "weekly-review-2026-05-03.pdf", "pdf_size_bytes": <n>}`)

#### Scenario: PDF generation completes within routine SLA

- **GIVEN** a synthetic 50-trade week (50 fills, 50 closed proposals, 50 risk_evaluations)
- **WHEN** `build_weekly_review_pdf(state)` is invoked
- **THEN** the call returns within 10 seconds (well within the 5-min routine SLA)
- **AND** the PDF is non-empty and validly formatted

### Requirement: Cross-context event subscriptions — orchestration consumes from research, trading, risk, approval, observability

The system SHALL subscribe to MessageBus events from upstream contexts in `OrchestrationService.start()`:
- `research.fact.added` (from R1) — feeds tier-3 audit by default; tier-1 if rule matches (e.g., FDA approval on watchlist).
- `trading.fill.received` (from T1) — feeds tier-3 audit by default; postmarket routine consumes accumulated fills.
- `risk.kill_switch.tripped` (from K1) — tier-1, immediate publish to P1 channels.
- `risk.proposal.rejected` (from K1) — tier-2, deferred to next routine digest.
- `approval.proposal.timed_out` (from P1) — tier-2, deferred.
- `observability.budget.block_100` (from O1) — tier-1.
- `observability.budget.warning_threshold` (from O1) — tier-2.

The orchestration context SHALL NOT publish events into upstream contexts (one-way subscription only). All subscription registration SHALL happen at app startup via `AlertFilter.subscribe_all(message_bus)`.

#### Scenario: Risk kill_switch event triggers immediate tier-1 emission

- **GIVEN** the AlertFilter has subscribed at startup
- **WHEN** K1's risk service publishes `risk.kill_switch.tripped` with payload `{"tenant_id": "t1", "reason": "daily_drawdown_5pct", "tripped_at": "2026-05-06T14:33:00Z"}`
- **THEN** within <1s, `alert_events` row inserts with `tier=1, source_event_name='risk.kill_switch.tripped'`
- **AND** `MessageBus("approval.alert.tier_1", ...)` is published with the original payload + classification metadata
- **AND** Telegram + Hermes channel subscribers (P1) receive the tier-1 alert and post to user devices within NFR-P3 p99 < 60s

#### Scenario: Observability budget warning routes to tier-2 digest

- **WHEN** O1 publishes `observability.budget.warning_threshold` with `{"tenant_id": "t1", "spent_usd": 40.00, "cap_usd": 50.00, "percent_used": 80.0}`
- **THEN** the AlertFilter classifies as TIER_2 (per `tier1_alerts.py::TIER_1_RULES` table)
- **AND** the event is added to the per-tenant tier-2 deque + persisted to `alert_events` with `tier=2`
- **AND** the next cron-fired routine drains the deque in `filter_alerts` node + includes the warning in the digest body
