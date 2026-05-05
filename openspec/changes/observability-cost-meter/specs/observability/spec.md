## ADDED Requirements

### Requirement: Cost meter records every LLM call to `api_cost_events`

The system SHALL provide `iguanatrader.contexts.observability.cost_meter::cost_meter(provider, model)` as a parametrised decorator factory. Functions wrapped with `@cost_meter(...)` SHALL persist one append-only `ApiCostEvent` row per invocation containing `tenant_id` (from `tenant_id_var`), `provider`, `model`, `node` (function qualname), `tokens_input`, `tokens_output`, `cost_usd` (computed from a price table), `cached` (from response object), `prompt_hash` (optional, when `IGUANATRADER_LOG_PROMPT_HASH=1`), `metadata` (provider extras), `routine_run_id` (NULL until slice O2 wires it), `correlation_id`, `created_at`. The decorator SHALL respect `tenant_id_var` and SHALL NOT silently swallow exceptions from the wrapped LLM call.

#### Scenario: Decorated function call records ApiCostEvent

- **WHEN** a function `synthesise_brief` is decorated with `@cost_meter(provider="anthropic", model="claude-3-5-sonnet")`
- **AND** the function is invoked inside a tenant context with `tenant_id_var` set
- **AND** the function returns an `LLMResponse(tokens_input=1200, tokens_output=350, cached=False)`
- **THEN** an `ApiCostEvent` row is inserted with `provider="anthropic"`, `model="claude-3-5-sonnet"`, `node="iguanatrader.contexts.research.brief.synthesise_brief"`, `tokens_input=1200`, `tokens_output=350`, `cached=FALSE`, and `cost_usd` computed from the Anthropic price table
- **AND** the `tenant_id` matches `tenant_id_var.get()`
- **AND** the row is append-only (UPDATE/DELETE rejected by `append_only_listener`)

#### Scenario: Cached response marks ApiCostEvent.cached TRUE with $0 cost

- **WHEN** the wrapped LLM SDK returns a response with `cached=True` (Anthropic prompt cache hit per NFR-I3)
- **THEN** the corresponding `ApiCostEvent` row has `cached=TRUE` and `cost_usd=0.00`
- **AND** the structlog event `observability.cost_meter.recorded` is emitted with `cached=true`

#### Scenario: LLM SDK exception propagates without recording phantom event

- **WHEN** the wrapped LLM SDK raises `anthropic.RateLimitError`
- **THEN** the decorator does NOT insert an `ApiCostEvent` row (no successful call to record)
- **AND** the exception propagates to the caller unchanged
- **AND** the structlog event `observability.cost_meter.upstream_error` is emitted with `provider`, `model`, `exc_info=True`

### Requirement: Perplexity throttle blocks excess QPS via in-process sliding window

The system SHALL provide `iguanatrader.contexts.observability.perplexity_throttle::PerplexityThrottle` enforcing a sliding-window rate limit of `config.perplexity.max_rpm` requests per 60-second window. The throttle's `acquire()` method SHALL evict timestamps older than 60 seconds, append the current timestamp if the window has capacity, and raise `PerplexityRateLimitError(retry_after_seconds=...)` otherwise. The throttle SHALL be process-local (in-memory deque + asyncio.Lock); multi-process awareness is deferred to v2.

#### Scenario: 11th call within 60s when max_rpm=10 raises rate limit error

- **GIVEN** `config.perplexity.max_rpm = 10`
- **WHEN** a caller invokes `throttle.acquire()` 10 times within 60 seconds — all succeed
- **AND** the 11th call is invoked at second 30 of the same window
- **THEN** the 11th call raises `PerplexityRateLimitError`
- **AND** the error's `retry_after_seconds` is approximately 30 (time until the oldest entry ages out of the window)
- **AND** the error renders as RFC 7807 `urn:iguanatrader:error:perplexity-rate-limit` with HTTP 429 via the global handler

#### Scenario: Calls outside the 60s window do not count

- **GIVEN** `config.perplexity.max_rpm = 5`
- **WHEN** 5 calls happen at second 0, then a 6th call at second 61
- **THEN** the 6th call succeeds (the second-0 call has aged out of the sliding window)

### Requirement: LLM routing picks model tier per task class

The system SHALL provide `iguanatrader.contexts.observability.llm_routing::route_llm(task_class)` returning the canonical `LLMTier` per `TaskClass`. The routing table SHALL be a hardcoded dict in `llm_routing.py` covering at minimum: `RESEARCH_BRIEF → claude-3-5-sonnet`, `ROUTINE_SUMMARY → claude-3-5-haiku`, `ALERTING → claude-3-5-haiku`, `COMPLEX_SYNTHESIS → claude-3-opus`, `GPT_FALLBACK → gpt-4o-mini`. The routing decision SHALL emit a structlog `observability.llm.route_chosen` event with `task_class`, `tier`, `tenant_id`, `reason` (e.g. `"baseline"`, `"budget_warn_downgrade"`, `"budget_block_fallback"`).

#### Scenario: Research brief task class routes to Sonnet

- **WHEN** a caller invokes `route_llm(TaskClass.RESEARCH_BRIEF)` with budget state `OK`
- **THEN** the returned tier is `LLMTier.CLAUDE_3_5_SONNET`
- **AND** the structlog event `observability.llm.route_chosen` is emitted with `tier="claude-3-5-sonnet"` and `reason="baseline"`

#### Scenario: Alerting task class routes to Haiku

- **WHEN** a caller invokes `route_llm(TaskClass.ALERTING)` with budget state `OK`
- **THEN** the returned tier is `LLMTier.CLAUDE_3_5_HAIKU`

### Requirement: Budget gate warns at 80% and blocks at 100% of monthly cap

The system SHALL provide `iguanatrader.contexts.observability.budget::check_budget(tenant_id)` returning a `BudgetState` with status `OK | WARN_80 | BLOCK_100`. The function SHALL aggregate `SUM(cost_usd) FROM api_cost_events WHERE tenant_id = :t AND created_at >= start_of_month_utc()` and compare against `tenants.feature_flags["llm_budget_usd"]` (default 50.00). The `route_llm()` function SHALL invoke `check_budget()` on every call; `WARN_80` SHALL auto-downgrade `claude-3-5-sonnet → claude-3-5-haiku` and `claude-3-opus → claude-3-5-sonnet` and emit structlog `observability.budget.warning_threshold` (once per crossing per tenant per month); `BLOCK_100` SHALL raise `BudgetExceededError` (HTTP 402, `urn:iguanatrader:error:budget-exceeded`).

#### Scenario: Spend at 79% returns OK

- **GIVEN** `tenants.feature_flags["llm_budget_usd"] = 50.00`
- **AND** `SUM(cost_usd) for current month = 39.50` (79%)
- **WHEN** `check_budget(tenant_id)` is invoked
- **THEN** the result is `BudgetState(status=OK, percent_used=79.0, remaining_usd=10.50)`
- **AND** subsequent `route_llm(TaskClass.RESEARCH_BRIEF)` returns `claude-3-5-sonnet` (no downgrade)

#### Scenario: Spend crosses 80% — next routing call downgrades

- **GIVEN** the cap is 50.00 and current month spend is 40.00 (80%)
- **WHEN** `route_llm(TaskClass.RESEARCH_BRIEF)` is invoked
- **THEN** the returned tier is `LLMTier.CLAUDE_3_5_HAIKU` (downgraded from sonnet)
- **AND** the structlog event `observability.budget.warning_threshold` is emitted (once for this crossing)
- **AND** the structlog event `observability.llm.route_chosen` is emitted with `reason="budget_warn_downgrade"`

#### Scenario: Spend at 100% — BLOCK_100 raises BudgetExceededError

- **GIVEN** the cap is 50.00 and current month spend is 50.00
- **WHEN** `route_llm(TaskClass.RESEARCH_BRIEF)` is invoked
- **THEN** the call raises `BudgetExceededError`
- **AND** the global RFC 7807 handler renders `{"type": "urn:iguanatrader:error:budget-exceeded", "title": "Monthly LLM Budget Exceeded", "status": 402, "detail": "...", "tenant_id": "...", "spent_usd": 50.00, "cap_usd": 50.00}`

### Requirement: Replay cache provides deterministic LLM responses across test runs

The system SHALL provide `iguanatrader.contexts.observability.replay_cache::replay_cache(scenario)` as a context manager. When `IGUANATRADER_LLM_REPLAY=1` is set, entering the context SHALL patch LLM SDK call sites to return the response stored in `tests/fixtures/replay_cache/<scenario>.json`; cache misses SHALL raise `ReplayCacheMissError`. When `IGUANATRADER_LLM_REPLAY` is unset, the context manager SHALL be a no-op (production behaviour). Replay-cache hits SHALL still record an `ApiCostEvent` row with `cached=TRUE` and `cost_usd=0.00`.

#### Scenario: Test mode hit returns deterministic response

- **GIVEN** `IGUANATRADER_LLM_REPLAY=1` is set
- **AND** `tests/fixtures/replay_cache/research_brief_aapl.json` contains `{"tokens_input": 1500, "tokens_output": 400, "content": "..."}`
- **WHEN** test code runs `with replay_cache("research_brief_aapl"): response = synthesise_brief("AAPL")`
- **THEN** `response.tokens_input == 1500`, `response.tokens_output == 400`, `response.content == "..."`
- **AND** an `ApiCostEvent` row is inserted with `cached=TRUE` and `cost_usd=0.00`
- **AND** the same test invocation produces byte-identical results across N consecutive runs

#### Scenario: Test mode miss raises ReplayCacheMissError

- **GIVEN** `IGUANATRADER_LLM_REPLAY=1` is set
- **AND** no `tests/fixtures/replay_cache/missing_scenario.json` exists
- **WHEN** test code runs `with replay_cache("missing_scenario"): synthesise_brief("XYZ")`
- **THEN** the call raises `ReplayCacheMissError("Scenario 'missing_scenario' has no recorded fixture; record via IGUANATRADER_LLM_REPLAY_RECORD=1")`

#### Scenario: Production mode bypasses replay cache

- **GIVEN** `IGUANATRADER_LLM_REPLAY` is unset (production)
- **WHEN** code runs `with replay_cache("any_scenario"): synthesise_brief("AAPL")`
- **THEN** the real LLM call executes (no patching)
- **AND** the resulting `ApiCostEvent.cached` reflects whatever the SDK reported (Anthropic prompt cache status), NOT replay-cache state

### Requirement: structlog `RotatingFileHandler` rotates at 100MB with 7 backup files

The system SHALL provide `iguanatrader.contexts.observability.structlog_config::configure_logging(env)` as the authoritative structlog configuration entry point. In `IGUANATRADER_ENV in ("paper", "live")`, the configuration SHALL include a `logging.handlers.RotatingFileHandler` writing JSON lines to `logs/iguanatrader-{env}.log` with `maxBytes=100*1024*1024` (100 MB per NFR-O3) and `backupCount=7`. In `dev` and `test` envs, the file handler SHALL NOT be added; stdout-only matches the slice-5 baseline. `apps/api/src/iguanatrader/api/app.py::_configure_structlog()` SHALL delegate to this function.

#### Scenario: Log file reaches 100MB — rotation creates .log.1

- **GIVEN** `IGUANATRADER_ENV=paper` and `logs/iguanatrader-paper.log` is at 99.9MB
- **WHEN** the next log write pushes the file past 100MB
- **THEN** the handler renames `iguanatrader-paper.log` to `iguanatrader-paper.log.1` and opens a fresh `iguanatrader-paper.log`
- **AND** subsequent writes go to the fresh file
- **AND** when `iguanatrader-paper.log.7` already exists at next rotation, the oldest backup is dropped (per `backupCount=7`)

#### Scenario: Test env uses stdout-only

- **GIVEN** `IGUANATRADER_ENV=test`
- **WHEN** `configure_logging("test")` is invoked
- **THEN** structlog is configured with JSON-to-stdout only (no file handler)
- **AND** `logs/iguanatrader-test.log` is NOT created

### Requirement: `audit_log` supports per-tenant + cross-tenant `tenant_id IS NULL` rows

The system SHALL define `audit_log` (per migration `0006_observability_tables.py`) with `tenant_id UUID NULL`, where NULL values represent cross-tenant ops-global events (gitleaks pre-commit fail, license-boundary check fail, OTel emission failure, scheduler-level incident). The SQLAlchemy `tenant_listener._inject_tenant_filter` SHALL handle the NULL-tenant case for `audit_log`: when `tenant_id_var` is unset and the query targets `audit_log`, the filter SHALL add `WHERE tenant_id IS NULL`; when `tenant_id_var` is set, the filter SHALL match the current tenant. The append-only listener SHALL reject UPDATE/DELETE on `audit_log`.

#### Scenario: System actor inserts cross-tenant row

- **WHEN** the gitleaks pre-commit hook (system actor, no tenant context) inserts an `audit_log` row with `tenant_id=None`, `actor_kind="system"`, `event="security.gitleaks.violation"`
- **THEN** the row is persisted with `tenant_id IS NULL`
- **AND** the `tenant_listener.before_flush` does NOT raise `TenantContextMismatchError` for the NULL-tenant case (system context is allowed when target table is `audit_log`)

#### Scenario: Tenant-context query filters per-tenant rows only

- **GIVEN** `audit_log` has rows: 5 with `tenant_id='tenant-a'`, 3 with `tenant_id='tenant-b'`, 2 with `tenant_id=NULL`
- **WHEN** a request with `tenant_id_var=tenant-a` queries `SELECT * FROM audit_log`
- **THEN** the result returns the 5 `tenant-a` rows only (NOT the NULL rows, NOT the tenant-b rows)

#### Scenario: System-context query returns NULL-tenant rows only

- **WHEN** a system-context job (no `tenant_id_var` set) queries `audit_log`
- **THEN** the listener adds `WHERE tenant_id IS NULL` and returns the 2 NULL-tenant rows only

### Requirement: Cost dashboard publisher streams 5-minute snapshots via SSE

The system SHALL provide `iguanatrader.contexts.observability.cost_dashboard_publisher::publish_snapshot()` that aggregates `api_cost_events` from the last 5 minutes per tenant and emits a `MessageBus` event `observability.cost.snapshot` with payload `{tenant_id, period_start, period_end, total_usd, per_provider: {...}, per_model: {...}, calls_count, cache_hit_rate}`. The SSE endpoint `GET /api/v1/stream/costs/snapshots` (registered via slice-5 dynamic discovery) SHALL subscribe to the bus and stream snapshots to authenticated clients. Snapshot cadence SHALL be 5 minutes per NFR-O4.

#### Scenario: Active-session client receives snapshot every 5 minutes

- **GIVEN** an authenticated SvelteKit client subscribes to `/api/v1/stream/costs/snapshots`
- **AND** the publisher fires every 300 seconds
- **WHEN** the period ending at T contains 3 LLM calls totalling $1.23
- **THEN** the client receives an SSE event `cost.snapshot` with `total_usd: 1.23`, `calls_count: 3`, `period_end: T`
- **AND** subsequent events arrive at T+300s, T+600s, …

### Requirement: Carry-forward boundary-hardening items addressed in slice O1 scope

The system SHALL include the following carry-forward items from the slice-5 retro (chosen subset per design D9):

(a) `tenant_listener._inject_tenant_filter` SHALL skip filter injection for queries targeting only non-scoped tables (no `tenant_id` column) — allowing bootstrap-path helpers to use plain ORM and gotcha #28 to be resolved.

(b) `apps/api/src/iguanatrader/config/settings.py` SHALL add a boot-time guard that raises `ConfigError` when `IGUANATRADER_DEV_INSECURE_COOKIE=1` AND `IGUANATRADER_ENV=production`, blocking app startup.

(c) The CI pytest invocation in `.github/workflows/ci.yml` SHALL include `--cov-fail-under=80` so coverage threshold is enforced (not merely measured).

(d) `apps/api/README.md` SHALL document the local poetry-install pattern for Windows venvs (workaround sequence + when to fall back to CI for canonical test runs).

#### Scenario: Bootstrap-path query against non-scoped table works without raw SQL

- **GIVEN** `_inject_tenant_filter` is updated per (a)
- **AND** a developer writes `session.execute(select(Tenant).limit(1))` inside `routes/auth.py::login` zero-tenant guard (Tenant table has no `tenant_id` column — it IS the tenant table)
- **AND** `tenant_id_var` is unset (bootstrap path)
- **THEN** the query executes successfully (filter skipped because target table is not tenant-scoped)
- **AND** the slice-4 raw-SQL bypass in `routes/auth.py` collapses back to ORM

#### Scenario: Production env rejects DEV_INSECURE_COOKIE flag at boot

- **GIVEN** `IGUANATRADER_ENV=production` and `IGUANATRADER_DEV_INSECURE_COOKIE=1`
- **WHEN** `python -m iguanatrader.api` is invoked
- **THEN** the app fails to boot with `ConfigError("IGUANATRADER_DEV_INSECURE_COOKIE=1 is forbidden in production")`
- **AND** the exit code is non-zero

#### Scenario: CI pytest fails when coverage drops below 80%

- **GIVEN** the CI pytest job is configured with `--cov-fail-under=80`
- **WHEN** a slice introduces code without tests, dropping coverage to 78%
- **THEN** the pytest job exits non-zero with the explicit "Coverage failure: total of 78 is less than fail-under=80" message
- **AND** the PR's CI check fails
