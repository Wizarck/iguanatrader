## Why

Slices 1-5 (Wave 0 foundation) shipped a working FastAPI app with auth, persistence, RFC 7807 errors, and dynamic discovery — but the system has zero visibility into LLM spend, no Perplexity rate-throttle, no per-tenant budget gating, and no append-only audit trail. Every Wave-2+ slice that calls Anthropic / Perplexity (R2 EDGAR-FRED, R3 news catalysts, R5 brief synthesis, P1 approval channels for proposal authoring) will burn API credits silently and unpredictably. Without a cost meter + budget cap + structured audit log, the MVP cannot enforce FR40 (log every LLM call), FR41 (budget caps with auto-downgrade), FR42 (cost-per-trade), NFR-O1 (100% LLM persistence), NFR-O3 (log rotation 100MB / 7d), NFR-I3 (Anthropic prompt caching), or NFR-I4 (Perplexity rate-limit). Now is the right time because Wave 2 is about to land 5 slices in parallel that all assume the observability primitives exist; planting them here unblocks the wave.

This slice ALSO carries forward six items flagged in `retros/api-foundation-rfc7807.md` §"Carry-forward to next change" — the items that fit "observability + boundary hardening" land here; the rest are punted to slice O2 (`orchestration-scheduler-routines`) per design D9.

## What Changes

- **Bounded context `observability`** — new `apps/api/src/iguanatrader/contexts/observability/` package with `models.py`, `repository.py`, `cost_meter.py`, `perplexity_throttle.py`, `llm_routing.py`, `budget.py`, `replay_cache.py`, `cost_dashboard_publisher.py`, `structlog_config.py`, `otel.py`, `events.py`, `ports.py`. No code lives in shared kernel; the context owns its own state + ports.
- **Cost meter decorator** — `@cost_meter(provider="anthropic", model="claude-3-5-sonnet")` decorator wrapping any LLM-calling function. Persists `ApiCostEvent` (provider, model, node, tokens_input, tokens_output, cost_usd, cached, prompt_hash, metadata, routine_run_id, correlation_id) to `api_cost_events` (append-only, per-tenant). Captures via `tenant_id_var` from `contextvars` (NFR-O1, FR40, NFR-O7).
- **Perplexity rate-throttle (sliding window)** — `perplexity_throttle.py` enforces `config.perplexity.max_rpm` via 60-second sliding-window counter (in-memory + lock; no Redis MVP). Blocks excess QPS by raising `PerplexityRateLimitError` with retry-after hint; integration test exercises 11th call within 60s when max=10 (NFR-I4).
- **LLM routing decision** — `llm_routing.py::route_llm(task_class)` returns the model tier per task class (rule-based table: `research_brief → claude-3-5-sonnet`, `routine_summary → claude-3-5-haiku`, `alerting → claude-3-5-haiku`, `complex_synthesis → claude-3-opus`, `gpt_fallback → gpt-4o-mini`). Decision rationale logged via structlog `observability.llm.route_chosen` (FR39).
- **Budget gates per-tenant** — `budget.py::check_budget(tenant_id)` reads daily + weekly + monthly caps from `tenants.feature_flags["llm_budget_usd"]` (default $50/month). Returns `BudgetState(remaining_usd, percent_used, status)` where status is `OK | WARN_80 | BLOCK_100`. WARN_80 emits structlog `observability.budget.warning_threshold` + auto-downgrades to cheaper tier; BLOCK_100 raises `BudgetExceededError` (FR41).
- **Replay cache for deterministic test runs** — `replay_cache.py` provides `with replay_cache(scenario="research_brief_aapl"):` context manager that, in test mode (`IGUANATRADER_LLM_REPLAY=1`), returns cached responses from `tests/fixtures/replay_cache/<scenario>.json`. Cache miss in replay mode raises `ReplayCacheMissError`. Production mode bypasses entirely. Marks `ApiCostEvent.cached = TRUE` on hit (NFR-O1 column semantics).
- **Cost dashboard publisher** — `cost_dashboard_publisher.py` aggregates `api_cost_events` per 5-minute bucket and publishes via `MessageBus` event `observability.cost.snapshot`. SSE endpoint `api/sse/costs.py` subscribes and streams snapshots to dashboard clients (NFR-O4 — every 5min in active session).
- **Structlog config (RotatingFileHandler)** — `structlog_config.py::configure_logging(env)` extends the slice-5 `_configure_structlog()` with a `RotatingFileHandler` writing JSON lines to `logs/iguanatrader-{env}.log` with `maxBytes=100*1024*1024` (100MB per NFR-O3) and `backupCount=7` (7-day retention). `apps/api/src/iguanatrader/api/app.py::_configure_structlog()` calls into this module — deliberate exception to "no shared infra edits" documented in design D6.
- **OTEL stub** — `otel.py` declares the OpenTelemetry tracer/meter ports + initializer scaffold but defers actual exporter wiring to v2 SaaS. The stub provides decorators (`@traced`, `@metered`) that are no-ops in MVP but become wire-compatible once OTEL collector lands. Documented in design D7.
- **Migration `0006_observability_tables.py`** — adds `api_cost_events` (append-only per-tenant, FR40), `config_changes` (append-only per-tenant, FR47), `audit_log` (append-only with per-tenant + cross-tenant `tenant_id IS NULL` rows for ops-global events per data-model §7.1, NFR-O5).
- **Routes + SSE + DTOs** — `api/routes/costs.py` (`GET /costs/summary`, `GET /costs/by-provider`, `GET /costs/per-trade`), `api/sse/costs.py` (`GET /stream/costs/snapshots`), `api/dtos/observability.py` (`ApiCostEventDTO`, `BudgetStateDTO`, `CostSnapshotDTO`).
- **Carry-forward items (chosen subset per design D9)**: (a) fix `_inject_tenant_filter` to skip non-scoped tables, (b) boot-time guard rejecting `IGUANATRADER_DEV_INSECURE_COOKIE=1` when `IGUANATRADER_ENV=production`, (c) `--cov-fail-under=80` in CI pytest invocation, (d) document local poetry-install pattern for Windows venv. Punted to slice O2: ORM-SELECT-in-`get_current_user` lint rule, Argon2 auto-rehash (rationale in D9).

## Capabilities

### New Capabilities

- `observability`: cost meter recording every LLM call to `api_cost_events`; Perplexity sliding-window rate-throttle; rule-based LLM routing per task class; per-tenant monthly budget cap with WARN_80 / BLOCK_100 semantics; deterministic replay cache for tests; structlog `RotatingFileHandler` 100MB/7d; OTEL port stub; `audit_log` per-tenant + cross-tenant scope; `config_changes` diff history.

### Modified Capabilities

- **`api-foundation`**: `apps/api/src/iguanatrader/api/app.py::_configure_structlog()` is extended (NOT replaced) by `contexts/observability/structlog_config.py::configure_logging()`. The slice-5 in-process JSON-to-stdout config remains the default for tests; the file-rotation handler is added for `IGUANATRADER_ENV in ("paper","live")`. Wire-format identical (JSON lines); only the destination handler set differs. Documented as deliberate exception in design D6.

## Impact

- **Affected code (slice-O1-owned, write-allowed)**:
  - `apps/api/src/iguanatrader/contexts/observability/{__init__,models,repository,cost_meter,perplexity_throttle,llm_routing,budget,replay_cache,cost_dashboard_publisher,structlog_config,otel,events,ports}.py` (NEW — full bounded context).
  - `apps/api/src/iguanatrader/migrations/versions/0006_observability_tables.py` (NEW — `api_cost_events`, `config_changes`, `audit_log`).
  - `apps/api/src/iguanatrader/api/routes/costs.py` (NEW — dynamic discovery picks it up; no edit to `app.py` per slice-5 contract).
  - `apps/api/src/iguanatrader/api/sse/costs.py` (NEW — same dynamic-discovery pattern).
  - `apps/api/src/iguanatrader/api/dtos/observability.py` (NEW — typed DTOs flow into shared-types via slice-5 typegen pipeline).
  - `apps/api/tests/integration/test_perplexity_throttle.py` + `test_cost_meter.py` + `test_budget_gates.py` + `test_replay_cache.py` + `test_audit_log_scope.py` + `test_observability_routes.py` (NEW).
  - `apps/api/src/iguanatrader/persistence/tenant_listener.py` (MOD — `_inject_tenant_filter` carry-forward fix; skips non-scoped tables).
  - `apps/api/src/iguanatrader/api/app.py` (MOD — `_configure_structlog()` delegates to `contexts/observability/structlog_config.py::configure_logging(env)`; deliberate exception to "no shared infra edits" — documented design D6).
  - `apps/api/src/iguanatrader/config/settings.py` (MOD — boot-time guard rejecting `IGUANATRADER_DEV_INSECURE_COOKIE=1` when `IGUANATRADER_ENV=production`).
  - `.github/workflows/ci.yml` (MOD — add `--cov-fail-under=80` to pytest invocation).
  - `apps/api/README.md` (MOD — document Windows poetry-install workaround).
- **Affected code (read-only consumed)**:
  - `iguanatrader.shared.{kernel.MessageBus, types.Money, errors.IguanaError, contextvars.tenant_id_var, ports.Port, backoff, heartbeat}` (slice 2).
  - `iguanatrader.persistence.{session, append_only_listener, tenant_listener}` (slice 3) — append-only listener marks `api_cost_events`, `config_changes`, `audit_log` as `__tablename_is_append_only__ = True`.
  - `iguanatrader.api.errors` (slice 5) — new `IguanaError` subclasses (`BudgetExceededError`, `PerplexityRateLimitError`, `ReplayCacheMissError`) flow through the global RFC 7807 handler.
- **Affected APIs**: 4 new endpoints — `GET /api/v1/costs/summary`, `GET /api/v1/costs/by-provider`, `GET /api/v1/costs/per-trade`, `GET /api/v1/stream/costs/snapshots`. All RFC 7807 on error per slice-5 contract.
- **Affected dependencies**:
  - `opentelemetry-api>=1.25,<2.0` — runtime dep for the OTEL port stub (api only; no exporter / SDK in MVP).
  - No new frontend deps (slice W1 will consume the new DTOs via `@iguanatrader/shared-types` once typegen regenerates).
- **Prerequisites**:
  - `api-foundation-rfc7807` (slice 5) — provides the dynamic-discovery contract for `routes/costs.py` + `sse/costs.py`, the global RFC 7807 handler chain, and the typegen pipeline.
  - `persistence-tenant-enforcement` (slice 3) — provides the SQLAlchemy listener + `__tablename_is_append_only__` contract.
  - `shared-primitives` (slice 2) — provides `MessageBus`, `Money`, `tenant_id_var`, `IguanaError`.
- **Capability coverage** (per `docs/openspec-slice.md` row O1): FR39 (LLM routing), FR40 (cost logging), FR41 (budget caps + auto-downgrade), FR42 (cost-per-trade), NFR-O1 (100% persistence), NFR-O3 (log rotation 100MB/7d), NFR-O4 (5min dashboard), NFR-O7 (`prompt_hash` optional in metadata), NFR-I3 (Anthropic prompt caching enabled — observed via `cached` column), NFR-I4 (Perplexity rate-limit).
- **Out of scope** (per `docs/openspec-slice.md` row O1 + design D9):
  - Scheduler routines (premarket / midday / postmarket / weekly review) — slice O2 owns FR43-FR44.
  - Concrete LLM provider adapters (Anthropic SDK wiring, Perplexity HTTP client) — those land in research / approval slices that consume the cost meter decorator.
  - Cost dashboard SvelteKit UI — slice W1 dashboard skeleton + later UI slice consume the SSE.
  - Carry-forward items punted to O2: ORM-SELECT-in-`get_current_user` pre-commit lint rule, Argon2 auto-rehash on login, L2 review marker schema discoverability (rationale: latter two are auth-context concerns; lint rule is best authored alongside O2's scheduler entry-point lint).
  - Real OTEL exporter wiring — port stub only; v2 SaaS lands the collector.
