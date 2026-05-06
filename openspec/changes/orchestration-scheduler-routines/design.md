## Context

Slice O2 plants the **orchestration bounded context** — the cron-driven scheduler, four LangGraph routine workflows, the tier-1/2/3 alert classification engine, and the weekly PDF report generator. Wave 2 cumulative state at slice-O2 start:

- Slice 1-5 ✅ — monorepo, shared kernel (`MessageBus`, `Money`, `tenant_id_var`, `IguanaError`), persistence (`tenant_listener`, `append_only_listener`), auth, RFC 7807 + dynamic discovery + typegen.
- R1 ✅ — `research_facts` bitemporal schema (the `collect_facts` LangGraph node queries this).
- T1 ✅ — `trade_proposals`, `fills`, `equity_snapshots` (midday/postmarket routines summarize from these).
- K1 ✅ — `risk.kill_switch.tripped` MessageBus events (tier-1 alert filter subscribes).
- P1 ✅ — Telegram + Hermes channels with 17-command dispatcher (tier-1 alerts emit via `MessageBus.publish("approval.alert.tier_1", ...)` consumed by these channels).
- O1 ✅ — `cost_meter` decorator, `check_budget(tenant_id)`, `route_llm(task_class)`, `structlog_config`, `audit_log` (the alert tier-3 destination).

The challenge is **operational**, not algorithmic. Schedulers in Python applications are notorious for three failure modes: (1) **memory leaks** when long-running schedulers retain job execution history forever (mitigation: `SQLAlchemyJobStore` instead of `MemoryJobStore`), (2) **DST timezone bugs** when ET-aware crons fire twice on fall-back or zero times on spring-forward (mitigation: `zoneinfo` Python 3.11+ stdlib + property test sweep across DST boundaries), (3) **mid-routine crash recovery** where a routine starts, persists `routine_runs.status='running'`, then the process dies → orphan row stuck at `running` forever (mitigation: bootstrap-time janitor that ages out `running` rows older than 2× SLA timeout to `status='timeout'`). The slice addresses all three explicitly via the decisions below.

The **LangGraph workflow choice** is deliberate: each routine is naturally a 4-step DAG (`collect → synthesize → filter → publish`), and LangGraph gives us per-node observability, retries, and a checkpointer for free. MVP uses the memory checkpointer (routines run <5min — no need to survive process restart mid-routine); v2 SaaS may add a persistent checkpointer if routines grow long enough to warrant it.

The **tier-1 alert filter** sits at the intersection of "rules engine" and "MessageBus subscriber" — it must be cheap (no LLM call to classify; rules-only) and synchronous-with-publication (a tier-1 alert must hit Telegram within 60s of the source event per NFR-P3). The filter therefore runs **inline** in the MessageBus subscriber callback, not as a deferred routine.

## Goals / Non-Goals

**Goals:**
- Plant the `orchestration` bounded context as a self-contained package — `service`, `scheduler`, `alert_filter`, `tier1_alerts`, `nodes/{premarket,midday,postmarket,weekly_review}`, `report_pdf`, `prompts/*`, `models`, `repository`, `events`, `errors`.
- Use `apscheduler.schedulers.asyncio.AsyncIOScheduler` with `SQLAlchemyJobStore` (NOT `MemoryJobStore`) — long-uptime safe, memory-leak-free.
- Register 4 ET-aware cron jobs at app startup: premarket weekdays 06:30 ET, midday weekdays 12:30 ET, postmarket weekdays 16:30 ET, weekly_review Sundays 18:00 ET. DST handled by `zoneinfo`.
- Each routine implemented as a LangGraph `StateGraph` with `MemorySaver` checkpointer + 4 nodes (`collect_facts → synthesize_brief → filter_alerts → publish_digest`).
- Tier-1 alert filter (rules engine, no LLM) emits to P1 channels within 60s p99 (NFR-P3); tier-2 accumulates to next routine; tier-3 to `audit_log`.
- `routine_runs` table tracks every cron execution with start/end/status/duration_ms/cost_usd; SLA enforced at 5min p95 per routine (NFR-P3 routine path).
- `alert_events` table persists every classified event with tier + routing decision; SSE endpoint streams them to dashboard.
- Idempotent triggers via `uq_routine_runs_routine_name_scheduled_at` UNIQUE constraint; duplicate triggers fail-fast → `status='skipped_duplicate'`.
- LLM cost gating: every routine calls `check_budget(tenant_id)` at entry; `BLOCK_100` → fallback deterministic digest + `status='skipped_budget'`; `WARN_80` proceeds with auto-downgrade (O1 D4).
- Weekly PDF report via `reportlab` (FR44) — multi-page document with equity curve + trade table + cost breakdown + lessons + outlook.
- Failure modes: routine timeout (5min) → `status='timeout'` + tier-1 escalation alert; LLM down → fallback to deterministic digest; data missing → routine emits "insufficient data" digest with explicit list of missing facts.

**Non-Goals:**
- No trading routes (`api/routes/{trades,portfolio,strategies}.py`) — slice T4 owns those.
- No SvelteKit `/routines` or `/alerts` UI pages — backend-only slice; the SSE endpoint exists for W1 to consume but no UI page lands here.
- No per-tenant cron customisation MVP — single-user; v2 SaaS adds tenant-scoped cron config.
- No real OTLP wiring of `@traced` on routine nodes — O1 D7 stub remains no-op MVP.
- No persistent LangGraph checkpointer — memory checkpointer suffices for <5min routines.
- No backfill of historical routine runs — first cron fire of each routine post-deploy is the first row in `routine_runs`.
- No carry-forward of O1 D9 punted items (ORM-SELECT lint, Argon2 auto-rehash) — those punt to a future auth-hardening slice (D11).

## Decisions

### D1. APScheduler with `SQLAlchemyJobStore`, NOT `MemoryJobStore` — long-uptime memory-leak prevention

**Decision**: `scheduler.py::create_scheduler(engine)` returns an `AsyncIOScheduler` configured with:

```python
AsyncIOScheduler(
    jobstores={"default": SQLAlchemyJobStore(engine=engine, tablename="apscheduler_jobs")},
    executors={"default": AsyncIOExecutor()},
    job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
    timezone=ZoneInfo("America/New_York"),
)
```

`SQLAlchemyJobStore` persists job state to a single `apscheduler_jobs` table managed by APScheduler itself (out-of-band of our migrations — APScheduler creates the table on first start). `coalesce=True` collapses missed firings (e.g., if the process was down across 3 cron times, only one catch-up run executes). `max_instances=1` prevents overlapping executions of the same routine. `misfire_grace_time=300` (5 min) — if a cron fires but the executor is busy, wait up to 5 min before declaring the run missed.

**Alternatives considered**:
- **`MemoryJobStore`**: APScheduler's in-process default — leaks job execution history into the scheduler's internal `_pending_jobs` dict over months of uptime. Documented memory issue across the APScheduler 3.x line. Rejected.
- **Redis-backed `RedisJobStore`**: requires a Redis dependency MVP forbids (`docs/architecture-decisions.md` keeps moving parts low). v2 SaaS may switch.
- **External scheduler (cron / systemd timer + curl webhook)**: separates scheduling from app — but introduces a hard dependency on the host OS having cron + reliable wall-clock + a webhook receiver inside our app. Adds operational surface; rejected MVP.

**Rationale**: SQLAlchemy is already the persistence layer (slice 3); `SQLAlchemyJobStore` re-uses the engine + survives process restart cleanly. The `apscheduler_jobs` table is small (4 rows: one per cron job) and self-managed.

### D2. ET-aware crons with `zoneinfo` (Python 3.11+ stdlib) — DST sweep test in CI

**Decision**: All 4 cron jobs use `timezone=ZoneInfo("America/New_York")`. APScheduler's `CronTrigger` accepts the tz parameter and resolves DST internally. The triggers:

- `premarket`: `CronTrigger(day_of_week="mon-fri", hour=6, minute=30, timezone=ZoneInfo("America/New_York"))`
- `midday`: `CronTrigger(day_of_week="mon-fri", hour=12, minute=30, timezone=ZoneInfo("America/New_York"))`
- `postmarket`: `CronTrigger(day_of_week="mon-fri", hour=16, minute=30, timezone=ZoneInfo("America/New_York"))`
- `weekly_review`: `CronTrigger(day_of_week="sun", hour=18, minute=0, timezone=ZoneInfo("America/New_York"))`

A property test (`test_et_timezone_dst.py`) walks `freezegun.freeze_time` across 2026-03-08 (US spring-forward at 02:00 → 03:00 ET) and 2026-11-01 (US fall-back at 02:00 → 01:00 ET) and asserts each cron fires exactly once per scheduled day, not zero (skipped) or twice (re-fired).

**Alternatives considered**:
- **`pytz` (third-party)**: was the standard before Python 3.9; `zoneinfo` superseded it. No reason to add a dep.
- **UTC-only crons + manual ET conversion**: every routine would have to convert "is it 06:30 ET?" inside its body — error-prone, scatters tz logic across 4 files. Rejected.
- **Fixed UTC offsets (EST=−5, EDT=−4)**: ignores DST entirely; routines fire 1 hour off twice a year. Rejected.

**Rationale**: `zoneinfo` is the Python-native answer; APScheduler's `CronTrigger` integrates cleanly. The DST sweep test catches the failure modes deterministically.

### D3. LangGraph `StateGraph` per routine — 4 nodes, memory checkpointer MVP

**Decision**: each `nodes/<routine>.py` defines a `StateGraph[RoutineState]` with 4 nodes wired sequentially:

```
START → collect_facts → synthesize_brief → filter_alerts → publish_digest → END
```

`RoutineState` is a Pydantic model: `tenant_id, routine_run_id, scheduled_at, facts: list[Fact], digest: RoutineDigest | None, alerts_emitted: list[AlertEvent], errors: list[str]`. Each node mutates the state and returns the updated state. The `StateGraph` is compiled with `MemorySaver()` checkpointer (in-process; survives node failures within a single run; does NOT survive process restart).

**Per-node responsibilities**:
- `collect_facts(state)`: queries `research_facts` (R1), `trade_proposals` (T1), `risk_evaluations` (K1), `equity_snapshots` (T1) for the routine's relevant window. Window definitions: premarket = "since previous postmarket"; midday = "intraday so far"; postmarket = "today's session"; weekly_review = "past 7 calendar days". Returns updated state with `facts` populated.
- `synthesize_brief(state)`: calls `route_llm(TaskClass.ROUTINE_SUMMARY)` (returns haiku for premarket/midday/postmarket; sonnet for weekly_review per task class registration; opus only if explicitly forced via routine config). Renders `prompts/<routine>.md` Jinja2 template with state.facts; sends to LLM SDK wrapped in `@cost_meter(provider, model)` (decorator captured tenant_id from contextvars). Returns updated state with `digest` populated.
- `filter_alerts(state)`: iterates state.facts + state.digest.alert_candidates through `alert_filter.classify_event`. Tier-1 events get published immediately to `MessageBus("approval.alert.tier_1", ...)`. Tier-2 events get added to digest body. Tier-3 events get persisted to `audit_log` only. Returns updated state with `alerts_emitted` populated.
- `publish_digest(state)`: persists final digest to `routine_runs.digest_payload`, sets `status='success'`, emits MessageBus event `orchestration.<routine>.digest_published` with payload + ISO 8601 UTC timestamps. P1 channels' subscribers pick this up and post to Telegram/Hermes.

**Alternatives considered**:
- **Plain async function chain (no LangGraph)**: works for the 4-node DAG but loses (a) per-node observability (LangGraph emits `node_started/node_finished` events natively), (b) checkpoint-resume on node failure, (c) future extensibility (e.g., a sub-graph for "research deep dive" can plug in as a node). MVP gain is small; future cost is high.
- **Celery task chain**: requires Redis + worker pool — overkill MVP; v2 SaaS may consider.
- **Prefect / Dagster pipeline**: heavier orchestration framework; routines are <5min single-process — overkill.

**Rationale**: LangGraph is already in the dependency tree (research-brief-synthesis R5 uses it for the multi-method brief). Reusing it here keeps the toolchain narrow; the abstractions (StateGraph, checkpointer, node decorators) match the routine shape exactly.

### D4. Tier-1 alert filter is a rules engine subscribing to MessageBus inline — NOT a polling loop

**Decision**: `alert_filter.py::AlertFilter.subscribe_all(message_bus)` is invoked at app startup in `service.py::start()`. It registers synchronous-with-publication subscribers for the canonical event names:

- `risk.kill_switch.tripped` → tier-1
- `trading.ibkr.disconnected_90s` → tier-1
- `research.fda.approval_on_watchlist` → tier-1
- `research.insider.buy_pct` (with `pct ≥ 10`) → tier-1
- `observability.budget.block_100` → tier-1
- `approval.proposal.timed_out` → tier-2
- `trading.fill.received` → tier-3
- `research.fact.added` → tier-3 (unless on watchlist)
- ... (full table in `tier1_alerts.py::TIER_1_RULES`)

When a tier-1 event arrives, the subscriber callback (a) records `alert_events` row with `tier=1, routing_decision={"emitted_to_channels": ["telegram", "hermes"]}`, (b) publishes `MessageBus.publish("approval.alert.tier_1", {payload, source_event_name, source_event_id})` synchronously — P1's Telegram/Hermes channels are already subscribed and will fan-out to the user device. Tier-2 events go to a per-tenant in-memory queue that the next cron-fired routine drains in `filter_alerts`. Tier-3 events go straight to `audit_log` via `AuditLogRepository.insert(...)`.

**Alternatives considered**:
- **Polling loop on `alert_events` table**: introduces 60s+ latency depending on poll interval — violates NFR-P3 (p99 < 60s). Rejected.
- **LLM-based tier classifier**: $$$$ + latency; tier-1 needs to be deterministic and cheap.
- **Tier-1 filter as a separate routine that fires every 30s**: same 60s+ latency problem; also wasteful (most ticks have nothing to classify).

**Rationale**: NFR-P3 (p99 < 60s for tier-1) is achievable only if the filter runs synchronously with publication. Rules-based classification is fast (<1ms per event), deterministic, and free of LLM cost. MessageBus's `subscribe()` contract from slice 2 is exactly the right primitive.

### D5. `routine_runs` is "mutable-then-frozen" — exception to append-only documented inline

**Decision**: `routine_runs` deliberately violates the strict append-only contract from slice 3. The lifecycle is:

1. **INSERT** at routine entry: `status='running', started_at=now, ended_at=NULL, duration_ms=NULL, cost_usd=NULL, digest_payload=NULL`.
2. **UPDATE** at routine exit: `status='success'|'timeout'|'error'|'skipped_budget'|'skipped_duplicate', ended_at=now, duration_ms=..., cost_usd=..., digest_payload=...`.
3. **No further updates** after step 2 — the row is effectively frozen.

The `append_only_listener` from slice 3 is configured to **allow UPDATE on `routine_runs` only when `status='running' → status IN terminal states`**; any other UPDATE pattern raises `AppendOnlyViolationError`. This is implemented via a row-level CHECK constraint on the `status` transitions plus a per-table override in the listener whitelist (`__tablename_is_append_only__ = "running_to_terminal"` — special string the listener interprets).

**Rationale**: a strictly append-only routine_runs would require two tables (`routine_runs_started` + `routine_runs_completed` with a JOIN) — clumsy for the dashboard query "how is the current routine doing?". The "mutable-then-frozen" pattern is a documented exception (gotcha #64 candidate post-merge). The CHECK constraint enforces that the only legal transitions are `running → terminal`; no row can be re-opened or revised.

**Alternatives considered**:
- **Two tables (`routine_runs_started`, `routine_runs_completed`)**: doubles the surface; query JOIN every time. Rejected.
- **Strictly append-only routine_runs (each state change is a new row)**: dashboard query becomes a window function over partitions per `routine_run_id` — slow, ugly. Rejected.
- **No status tracking; rely on logs only**: violates NFR-P3 measurement (we can't query `SELECT MAX(duration_ms) FROM routine_runs WHERE routine_name='premarket' AND ...` for SLA reporting). Rejected.

**Bootstrap janitor**: at app startup, `service.py::clean_orphan_runs()` runs `UPDATE routine_runs SET status='timeout', ended_at=now, error_message='process_crashed_during_routine' WHERE status='running' AND started_at < now - interval '10 minutes'` — catches orphan rows from previous process crashes (the 10-min threshold is 2× the 5-min routine SLA).

### D6. LLM cost budget gating runs at routine entry, not per-LLM-call

**Decision**: `service.py::run_routine(name, scheduled_at, tenant_id)` calls `check_budget(tenant_id)` at the very top, before instantiating the LangGraph workflow. Three branches:

- `OK`: proceed normally.
- `WARN_80`: proceed; the `route_llm()` call inside `synthesize_brief` will auto-downgrade per O1 D4 (sonnet → haiku, opus → sonnet). The routine completes with cheaper model, slightly less rich output.
- `BLOCK_100`: skip the LangGraph workflow entirely. Persist `routine_runs` with `status='skipped_budget'`, `digest_payload={"fallback": True, "reason": "budget_block_100", "deterministic_summary": <facts as bullet points>}`. Emit a tier-1 alert `observability.budget.block_100_routine_skipped` so the operator knows to raise the cap.

The fallback "deterministic digest" is a templated string assembled by `nodes/<routine>.py::build_fallback_digest(facts)` — no LLM call, just `len(facts)` bullets summarising raw facts ("3 new research_facts since previous routine, 2 fills overnight, 0 risk_evaluations rejected"). This guarantees that even at 100% budget the user gets a cron-fired notification, just without the synthesised narrative.

**Alternatives considered**:
- **Per-LLM-call check**: O1 D4 already does this inside `route_llm()`. Doing it again at routine entry is a quick fast-fail that avoids spinning up the LangGraph runtime if the budget is exhausted. Cheaper.
- **Routine-level budget cap** (e.g., "no routine spends more than $0.10"): premature; O1 D4 monthly cap suffices for MVP.

**Rationale**: routine entry is a natural chokepoint; checking once there saves the LangGraph spin-up cost when over budget. The fallback deterministic digest preserves the cron-fired signal even at 100%.

### D7. Weekly PDF via `reportlab`, NOT WeasyPrint or HTML→PDF

**Decision**: `report_pdf.py::build_weekly_review_pdf(state) -> bytes` uses `reportlab.platypus` (Flowable / Paragraph / Table / Spacer) to assemble:

1. Title page: "Weekly Review — Week N / 2026", date range (ISO 8601 UTC), tenant name.
2. Equity curve page: matplotlib-rendered PNG embedded via `reportlab.platypus.Image` (matplotlib already in research-brief deps tree).
3. Trade table page: rows = closed trades this week; columns = symbol, entry, exit, P&L, holding period, strategy, reasoning excerpt, decision marker.
4. Strategy breakdown page: per-strategy P&L + win rate + avg holding.
5. Cost breakdown page: per-LangGraph-node breakdown of LLM spend (from `api_cost_events.routine_run_id` rolled up).
6. Lessons section: LLM-extracted lessons from the week's trade reasoning (one paragraph per lesson, 3-5 lessons typical).
7. Outlook section: next week's earnings calendar + macro events from R2/R3 sources.

The PDF is published as a MessageBus event `orchestration.weekly_review.pdf_ready` with `{tenant_id, pdf_bytes, filename: "weekly-review-{iso_date}.pdf"}` — P1 Telegram channel uploads as document; Hermes uses the file link path (its API does not accept binary directly).

**Alternatives considered**:
- **WeasyPrint**: HTML→PDF — beautiful CSS support, but requires Cairo + Pango on Windows (gotcha #19 territory: binary deps on Windows are painful). Rejected MVP.
- **HTML+Playwright print-to-PDF**: requires headless browser; heavyweight; we already have Playwright for tier-2 scraping but spinning it up for a PDF is overkill.
- **Markdown→pandoc→PDF**: requires LaTeX install — same Windows friction.

**Rationale**: `reportlab` is pure Python, pip-installable on Windows without binary deps. The output is less "beautiful" than HTML+CSS but FR44 only requires the content — equity curve + trades + cost + lessons + outlook — not visual polish. Visual polish is a v1.0 launch concern.

### D8. Routine timeout = 5min hard kill via `asyncio.wait_for`; emits tier-1 escalation

**Decision**: `service.py::run_routine` wraps the LangGraph invocation in `asyncio.wait_for(graph.ainvoke(state), timeout=300)`. On `asyncio.TimeoutError`:

1. The current node is cancelled (LangGraph's `ainvoke` cooperates with cancellation — verified in integration test).
2. `routine_runs.status` updates to `'timeout'`, `ended_at=now`, `error_message='exceeded_5min_sla'`.
3. A tier-1 alert publishes: `orchestration.routine.timeout` event with `{routine_name, scheduled_at, duration_ms=300000, last_node}`.
4. The next cron fire of the same routine proceeds normally (no cascading timeout).

**Rationale**: NFR-P3 (5min p95 routine SLA) requires a hard ceiling. Without `asyncio.wait_for`, a stuck LLM call could keep the routine running for hours. The tier-1 escalation tells the operator *immediately* that something is wrong (LLM provider down? Network partition? IBKR API hung?).

**Alternatives considered**:
- **Soft timeout (mark `status='slow'` but let it complete)**: dashboard becomes confusing — is the routine still running? When will the next one fire? Rejected.
- **Per-node timeout**: more granular but overkill for 4 nodes; the routine-level timeout suffices.

### D9. Idempotency via `uq_routine_runs_routine_name_scheduled_at` — duplicate triggers fail-fast

**Decision**: `routine_runs` has `UNIQUE(routine_name, scheduled_at)` (composite). When APScheduler's `coalesce=True` + `max_instances=1` defends against most duplicate cases, the UNIQUE constraint is the belt-and-braces backstop for: process restart that re-fires a missed cron; manual `service.run_routine_now(name)` call colliding with a scheduled fire; clock skew that produces the same `scheduled_at` twice.

On `IntegrityError` at INSERT (duplicate violation): `service.py` catches the error, logs `orchestration.routine.duplicate_trigger` at WARNING level (not ERROR — this is expected on rare occasions), inserts a NEW `routine_runs` row with a derived `scheduled_at = original_scheduled_at + 1ms` and `status='skipped_duplicate'` to keep audit trail visible. The original (winning) routine continues unaffected.

**Alternatives considered**:
- **Distributed lock (Redis)**: requires Redis MVP forbids.
- **In-process `asyncio.Lock` keyed by routine_name**: works for single-process MVP but does not survive across restart-collision scenarios.
- **Best-effort, no UNIQUE**: would silently allow double-runs in restart scenarios; violates idempotency contract.

**Rationale**: UNIQUE constraint is a database-enforced primitive that always wins; the IntegrityError handler is a 3-line catch-and-log.

### D10. Manual trigger endpoint deferred — `service.run_routine_now(name)` exposed via CLI only

**Decision**: `cli/orchestration.py` (lands in slice T4 or a future ops slice) will expose `iguanatrader ops run-routine <name>` for manual re-trigger. Slice O2 plants `service.run_routine_now(name, tenant_id)` as the public service method (so the future CLI can call it) but does NOT add a REST endpoint or CLI subcommand here.

**Rationale**: scope discipline. The cron path is the production path; manual triggers are a debugging convenience. Adding the route + CLI in this slice would touch surface area outside the orchestration context. Punted to a follow-up slice with its own design.

### D11. Carry-forward items from O1 D9 punted again — auth-context concerns out of scope

**Decision**: O1 D9 punted two carry-forward items to slice O2: ORM-SELECT-in-`get_current_user` lint rule + Argon2 auto-rehash. **Slice O2 punts these again** to a future auth-hardening slice. Rationale: they are `routes/auth.py` / `api/deps.py` concerns, not orchestration concerns — touching `routes/auth.py` from this slice would violate the bounded-context boundary and trigger a merge collision with any auth-concerned future slice. A "auth-hardening" slice (currently unplanned but easy to schedule when needed) is the right home.

Documented in `docs/gotchas.md` post-merge as "carry-forward items still pending auth-hardening slice (originally punted from slice 5 retro → O1 → O2)."

## Risks / Trade-offs

- **[Risk] APScheduler `SQLAlchemyJobStore` table conflicts with our migrations** → APScheduler creates `apscheduler_jobs` on first start (auto-DDL). If our `0007_orchestration_tables.py` migration also tried to create it, both fail. **Mitigation**: explicitly DO NOT include `apscheduler_jobs` in our migration; documented inline that the table is APScheduler-managed. Tested in `test_orchestration.py::test_apscheduler_jobs_table_auto_created`.

- **[Risk] DST transition fires routine zero or twice** → spring-forward (02:00 → 03:00 ET) skips 02:30; fall-back (02:00 → 01:00 ET) replays 01:30. Our routines fire at 06:30 / 12:30 / 16:30 / 18:00 — none of those are inside the 01:00-03:00 DST window, so the issue is theoretical. **Mitigation**: property test `test_et_timezone_dst.py` walks through both DST transitions + asserts each cron fires exactly once per scheduled day. If a future cron is added inside the DST window, the test will catch it.

- **[Risk] LangGraph memory checkpointer loses state on process restart mid-routine** → routine is interrupted, no checkpoint to resume from. **Mitigation**: routines are idempotent at the routine level (UNIQUE constraint via D9 + bootstrap janitor via D5). Mid-routine partial state is acceptable to lose — the next cron fire starts fresh. v2 SaaS may add persistent checkpointer if routines grow long enough that mid-routine resume becomes valuable.

- **[Risk] `reportlab` PDF generation is slow for large equity curves** → matplotlib + reportlab can take 2-5s for a 100-trade weekly. **Mitigation**: PDF generation runs inside the weekly_review routine's 5-min budget; 5s is fine. Profile in `test_report_pdf.py` to verify <10s for a 50-trade week.

- **[Risk] Tier-1 alert storm on a major event** → kill_switch trip + IBKR disconnect + budget block can cascade in seconds; the operator gets 3-5 Telegram messages within 60s. **Mitigation**: alert deduplication NOT in scope MVP — the operator wants to see all 5; v2 may add a 60s grouping window.

- **[Risk] `BudgetExceededError` raised inside LangGraph node propagates as graph error** → the routine crashes with an unhandled exception instead of cleanly recording `status='skipped_budget'`. **Mitigation**: the budget check at routine entry (D6) catches BLOCK_100 BEFORE the graph spins up; the only way `route_llm` raises mid-graph is if cumulative spend crosses 100% during the routine itself, which is rare given the routine entry check. If it does happen, the LangGraph error handler catches it + routes to `status='error'` with `error_message='budget_exceeded_mid_routine'`.

- **[Trade-off] D5 `routine_runs` "mutable-then-frozen" exception to append-only** — increases listener complexity (special-case for `routine_runs.status` transitions). The CHECK constraint + integration test (`test_routine_runs_status_transitions`) cover the matrix of legal/illegal updates. The single-table dashboard query benefit outweighs the listener complexity.

- **[Trade-off] D7 reportlab over WeasyPrint** — visual polish is lower than HTML+CSS would give. v1.0 SaaS launch may swap to HTML→Playwright→PDF when polish matters; MVP correctness over polish.

- **[Trade-off] D8 hard 5-min timeout cancels in-flight LLM calls** — the cancelled call still bills (the LLM provider doesn't refund). **Cost impact**: rare in practice (5min is generous for a 4-node routine); when it triggers, the cost meter records the partial call as usual (NFR-O1 100% persistence) so the operator sees the spend even on timeout.

## Migration Plan

This slice has no live deployment to migrate from. Deployment path:

1. Run `alembic upgrade head` on the slice branch — creates `routine_runs`, `alert_events`. APScheduler creates `apscheduler_jobs` on first scheduler start (out-of-band of Alembic; documented in migration docstring).
2. CI exercises migration on test SQLite + asserts `__tablename_is_append_only__` semantics for `alert_events` (strict) and `routine_runs` (running→terminal).
3. App startup (`service.py::start()`) registers 4 cron jobs in the scheduler. First production cron fire at next 06:30 ET (premarket) writes the first row in `routine_runs`.
4. Bot regenerates `packages/shared-types/src/index.ts` with new DTOs (`RoutineRunDTO`, `AlertEventDTO`, `RoutineDigestDTO`).
5. Merge to main; subsequent slices (T4 trading-routes-and-daemon) consume `routine_runs.cost_usd` for FR42 cost-per-trade calculations.

Rollback = revert PR + `alembic downgrade -1` (drops `0007_orchestration_tables.py`). The scheduler shutdown is idempotent; APScheduler's `apscheduler_jobs` table is left in place (no harm — empty table).

## Open Questions

- **Q**: Should weekly_review fire on Sundays 18:00 ET (per slice metadata) or Fridays 18:00 ET (per PRD §"WhatsApp del viernes anterior 18:00h ET, sin abrir hasta ahora")? **Tentative answer**: scope-note says Sundays; PRD journey example mentions Friday delivery for Sunday consumption. Implement Sundays 18:00 ET per scope note; document as gotcha if the PRD journey re-asserts Friday — easy to flip the cron value with no other code change.

- **Q**: Should tier-2 events that accumulate between routines have a TTL (e.g., drop after 24h)? **Tentative answer**: yes — in-memory queue trimmed at the start of each routine to "events from the last window only" (premarket=since previous postmarket; midday=intraday so far; postmarket=today; weekly=past 7 days). Documented in spec scenario.

- **Q**: Default routine timeout 5min — is that aggressive enough for weekly_review's 7-day data scan + PDF generation? **Tentative answer**: profile in CI integration test against a synthetic 100-trade week; if PDF generation pushes >5min, raise weekly_review-specific timeout to 10min while keeping daily routines at 5min. Configurable via `IGUANATRADER_ROUTINE_TIMEOUT_<NAME>_SECONDS` env vars (documented in `apps/api/README.md`).

- **Q**: Should `alert_events.routing_decision` be a structured enum (`emitted_to_telegram_hermes`, `deferred_to_digest`, `audit_only`) or a free-form JSON dict? **Tentative answer**: structured + extensible — JSONB column with a documented schema; CHECK constraint validates known keys. Allows future routing decisions (`emitted_to_dashboard_only`, `suppressed_by_dedup`) without migration.

- **Q**: Should the bootstrap janitor (D5) emit an alert when it cleans orphan rows? **Tentative answer**: yes — tier-2 alert (not tier-1; not user-facing critical) so the operator sees in the next routine digest "1 orphan routine_run was cleaned up at boot — likely process crash since last run". Surfaces operational issues without paging.
