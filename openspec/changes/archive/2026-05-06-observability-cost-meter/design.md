## Context

Slice O1 plants the **observability bounded context** that every Wave-2+ LLM-touching slice (R2 EDGAR-FRED, R3 news catalysts, R5 brief synthesis, P1 approval-channels for proposal authoring, T4 trading-routes-and-daemon for cost-per-trade) depends on. Wave 0 cumulative state at slice-O1 start:

- Slice 1-2 ✅ — monorepo + shared kernel (`MessageBus`, `Money`, `tenant_id_var`, `IguanaError`, `Port`).
- Slice 3 ✅ — SQLAlchemy + Alembic + `tenant_listener` (`_inject_tenant_filter` raises on bootstrap path — gotcha #28; this slice fixes it) + `append_only_listener`.
- Slice 4 ✅ — auth surface (`get_current_user`, JWT cookie). `IGUANATRADER_DEV_INSECURE_COOKIE=1` has no boot-time guard — this slice adds it.
- Slice 5 ✅ — dynamic discovery (`routes/<name>.py` + `sse/<name>.py` + `cli/<name>.py` autoload), global RFC 7807 handler chain, OpenAPI typegen, `_configure_structlog()` JSON-to-stdout (this slice extends with `RotatingFileHandler`).

The challenge is **boundary-defining**, not algorithmic. The observability primitives must be **opt-in by decorator** for callers (not magical middleware that wraps every request — most requests have nothing to do with LLM cost), and **append-only at the storage layer** (audit trail integrity is a hard NFR-SC2 requirement). The Perplexity throttle must work in-process (no Redis MVP — `docs/architecture-decisions.md` keeps the moving-parts count low). The replay cache must be a clear test-only path that production code cannot accidentally hit. The budget gate must support a soft warning (80%) AND a hard block (100%) — not just one threshold — because operators need lead time to react before the 100% block kicks in mid-routine.

The slice ALSO carries forward six items from `retros/api-foundation-rfc7807.md` §"Carry-forward to next change". Slicing these into THIS slice (vs. punting all to O2) is a deliberate scope choice (D9) — the items that fit "observability + boundary hardening" land here; the ones that fit "scheduler entry-point hardening" punt to O2.

## Goals / Non-Goals

**Goals:**
- Land the `observability` bounded context as a self-contained package — `cost_meter`, `perplexity_throttle`, `llm_routing`, `budget`, `replay_cache`, `cost_dashboard_publisher`, `structlog_config`, `otel`, `models`, `repository`, `events`, `ports`.
- Plant migration `0006_observability_tables.py` with `api_cost_events` (per-tenant append-only), `config_changes` (per-tenant append-only), `audit_log` (per-tenant + cross-tenant `tenant_id IS NULL` for ops-global events).
- Surface the cost meter as a `@cost_meter(provider, model)` decorator that wraps any LLM-calling function, persists `ApiCostEvent`, and respects `tenant_id_var`.
- Enforce Perplexity rate-limit via in-process sliding-window counter; raise `PerplexityRateLimitError` on overflow.
- Enforce per-tenant monthly budget cap with WARN_80 + BLOCK_100 semantics; auto-downgrade to cheaper model tier on WARN_80.
- Provide a deterministic replay cache for test runs (`IGUANATRADER_LLM_REPLAY=1`) — cache hit returns recorded response + marks `ApiCostEvent.cached=TRUE`; cache miss raises `ReplayCacheMissError` (test-mode only).
- Extend `_configure_structlog()` with `RotatingFileHandler` 100MB/7d in paper/live envs.
- Stub out OTEL ports for v2 SaaS — `@traced` / `@metered` decorators that are no-ops MVP.
- Land `routes/costs.py` + `sse/costs.py` per the slice-5 dynamic-discovery contract — zero edits to `app.py`.
- Carry-forward subset: fix `_inject_tenant_filter` for non-scoped tables; boot-time guard on `IGUANATRADER_DEV_INSECURE_COOKIE` in prod; `--cov-fail-under=80` in CI; document Windows poetry-install pattern.

**Non-Goals:**
- No concrete LLM provider adapters (Anthropic SDK init, Perplexity HTTP client) — those land in research / approval slices that consume the decorator.
- No scheduler / routine entry points (FR43-FR44) — slice O2 ships `routine_runs` table + scheduler.
- No cost-dashboard SvelteKit UI — slice W1 + later UI slice consume the SSE.
- No real OTEL exporter — stubs only; v2 SaaS lands the collector + Grafana / Tempo wiring.
- No Argon2 auto-rehash, no ORM-SELECT-in-`get_current_user` lint rule, no L2 marker-schema CI annotation — those are slice O2 carry-forward (D9).
- No `routine_runs` FK from `api_cost_events.routine_run_id` enforced — column is nullable + FK declared optional; slice O2 adds the table; until then `routine_run_id` stays NULL.

## Decisions

### D1. Cost meter is a `@cost_meter(provider, model)` decorator — NOT a context manager, NOT middleware

**Decision**: `apps/api/src/iguanatrader/contexts/observability/cost_meter.py::cost_meter` is a parametrised decorator factory. Usage: `@cost_meter(provider="anthropic", model="claude-3-5-sonnet")` wraps any function returning a Pydantic `LLMResponse` model with `tokens_input: int`, `tokens_output: int`, `cached: bool`. The decorator (a) reads `tenant_id_var.get()`, (b) starts a timer, (c) calls the wrapped function, (d) computes `cost_usd` from the provider+model price table, (e) inserts `ApiCostEvent` via repository, (f) returns the unwrapped response. Async-aware (`functools.wraps` + `inspect.iscoroutinefunction`).

**Alternatives considered**:
- **`with cost_meter(...)` context manager**: forces every caller to remember the `with` block; harder to retrofit into existing function signatures; no return-value capture path that's clean.
- **FastAPI middleware that intercepts every request**: most requests have nothing to do with LLM calls; middleware would need a heuristic to detect "did this request call an LLM?" — fragile. Wrong layer (request → response) for what's a function-call concern (LLM SDK invocation).
- **Implicit instrumentation via Anthropic / OpenAI SDK monkey-patching**: brittle across SDK versions; surprises developers; can't capture custom synthetic LLM scenarios (replay cache).

**Rationale**: explicit > implicit. Functions that call LLMs are a small, identifiable surface (research brief synthesizer, proposal authoring, alerting summarizer); decorating them is one line + reads cleanly. The decorator pattern composes with `@traced` / `@metered` (D7) and the replay cache (D5).

**Discoverability rule**: every callsite that hits an LLM SDK MUST be wrapped in `@cost_meter(...)`. CI test (`test_cost_meter.py`) asserts that calls to `anthropic.Anthropic().messages.create(...)` outside a `@cost_meter`-decorated stack frame are flagged (introspection via `inspect.stack()` in test fixture).

### D2. LLM routing is a rule-based table, NOT an ML classifier — task class enum drives the choice

**Decision**: `llm_routing.py::route_llm(task_class: TaskClass) -> LLMTier` returns the canonical model per task class. Hardcoded table in `llm_routing.py` (no DB lookup hot-path):

```
research_brief        → claude-3-5-sonnet     (high-quality synthesis, tool use)
routine_summary       → claude-3-5-haiku      (cheap, structured output)
alerting              → claude-3-5-haiku      (latency-sensitive, terse)
complex_synthesis     → claude-3-opus         (rare; weekly review FR44)
gpt_fallback          → gpt-4o-mini           (when Anthropic budget exhausted)
```

`TaskClass` is a `StrEnum`; the table is a `dict[TaskClass, LLMTier]`. Routing decision logged via structlog `observability.llm.route_chosen` with `task_class`, `tier`, `tenant_id`. Budget gate (D4) can override the choice with `WARN_80` downgrading from sonnet → haiku at the routing-decision layer.

**Alternatives considered**:
- **ML classifier on prompt content**: massive overkill MVP; introduces a dependency on a routing model + training data; deferred to v2.
- **DB-driven routing table** (`llm_routing_rules` table): adds operational surface (admin UI for routes); overkill for 5 task classes.
- **Per-tenant routing override**: every tenant uses the same defaults MVP; v2 SaaS may add `tenants.feature_flags["llm_routing_override"]`.

**Rationale**: 5 task classes, 5 well-known model tiers; a lookup table is the right abstraction. Future task classes added by editing the dict + a unit test.

### D3. Perplexity throttle uses an in-process sliding window, NOT token-bucket / Redis

**Decision**: `perplexity_throttle.py::PerplexityThrottle` keeps a `collections.deque[float]` of timestamps for the last 60 seconds, protected by `asyncio.Lock`. `acquire()` evicts entries older than 60s, checks `len(deque) < max_rpm`, appends current timestamp, returns; otherwise raises `PerplexityRateLimitError(retry_after_seconds=...)`. Singleton instance per process; `max_rpm` from `config.perplexity.max_rpm` (default 60).

**Alternatives considered**:
- **Token-bucket with leaky-rate refill**: more general; smoother; over-engineered for a single external API with a hard RPM limit.
- **Redis-backed sliding window**: required for multi-process / multi-tenant fairness in v2 SaaS; MVP is single-process, single-tenant — pure overhead.
- **Per-tenant throttle** (separate window per tenant): premature for single-tenant MVP; v2 ADR.

**Rationale**: minimal moving parts. The 60-second window is exact (no smoothing artefacts). Multi-process awareness deferred to v2 SaaS; documented as a v2 risk in `docs/architecture-decisions.md` (cross-reference, not a new ADR).

**NFR-I4 contract**: When the request rate would exceed `max_rpm`, the throttle blocks (raises) — it does NOT queue + delay. Callers receive `PerplexityRateLimitError`; routine-level retry logic (in slice O2) decides whether to wait + retry. This separates the throttle (mechanism) from the retry (policy).

### D4. Budget enforces 80% WARN + 100% BLOCK — and WARN_80 auto-downgrades the next routing decision

**Decision**: `budget.py::check_budget(tenant_id) -> BudgetState` aggregates `SUM(cost_usd) FROM api_cost_events WHERE tenant_id = :t AND created_at >= start_of_month` and compares against `tenants.feature_flags["llm_budget_usd"]` (default $50/month). Returns:
- `OK` (0-79%) — proceed normally.
- `WARN_80` (80-99%) — emit structlog `observability.budget.warning_threshold` once per crossing; `route_llm()` downgrades sonnet → haiku and opus → sonnet at the next call.
- `BLOCK_100` (100%+) — `route_llm()` raises `BudgetExceededError` (RFC 7807 status 402 — Payment Required); operator must raise the cap or wait for next month rollover.

The budget check runs **inside** `route_llm()` (single chokepoint) — no need to instrument every callsite.

**Alternatives considered**:
- **Single 100% block, no warn**: operators wake up to a wedged routine at 99.9% spend; no lead time. Rejected.
- **Configurable thresholds per tenant** (not just 80% / 100%): premature; default is a sane baseline. v2 SaaS may parametrise.
- **Hard block immediately at 100% without auto-downgrade lead-up**: same problem as above; the WARN_80 + downgrade gives ~20% spend headroom of cheap-model usage before the hard block.

**Rationale**: defence-in-depth. WARN_80 catches operator attention; the auto-downgrade gives runway; BLOCK_100 is the hard backstop. The single chokepoint (route_llm) keeps the budget logic in one place.

**FR41 contract**: "auto-downgrade to cheaper models on breach" maps to the WARN_80 path; "enforces caps" maps to BLOCK_100. Daily / weekly caps are out of scope MVP (monthly only); slice O2 may add daily/weekly if needed.

### D5. Replay cache is test-mode only — `IGUANATRADER_LLM_REPLAY=1` env flag gates entry

**Decision**: `replay_cache.py::replay_cache(scenario: str)` is a context manager. Behavior:
- Production (`IGUANATRADER_LLM_REPLAY` unset / "0"): no-op; `with replay_cache(...)` block runs the real LLM call.
- Test (`IGUANATRADER_LLM_REPLAY=1`): patches the LLM SDK call sites (via `unittest.mock.patch`-equivalent `contextvars`-scoped flag) to return responses from `tests/fixtures/replay_cache/<scenario>.json`. Cache hit marks the corresponding `ApiCostEvent.cached=TRUE` (so test runs still record cost events with $0 cost — cost = 0 when cached).
- Cache miss in test mode (no fixture file): raises `ReplayCacheMissError` with the scenario name + a hint to record fresh fixture (operator runs `IGUANATRADER_LLM_REPLAY_RECORD=1 pytest ...` to capture).

**Alternatives considered**:
- **VCR.py-style HTTP-level cassettes**: works for HTTP-based providers (Perplexity, OpenAI) but not for SDKs that bypass HTTP at the public-API layer (Anthropic Python SDK uses streaming generators internally). Brittle.
- **Just mock at the test-fixture level**: every test re-implements the mock; drift across tests; no central record-replay.
- **Always-on cache (production cache + test cache same code)**: production deserves real LLM calls (with caching at the SDK layer per NFR-I3 — Anthropic prompt caching); blending them obscures cost reality.

**Rationale**: test-mode-only keeps the production code path simple (decorator-only) and the cache mechanism dedicated to its actual purpose (test determinism). The `cached=TRUE` column flag in `ApiCostEvent` IS the production cache signal (Anthropic prompt caching reports the hit at SDK level — the decorator captures it from the response object, not from the replay cache).

### D6. `structlog_config.py` extends `app.py::_configure_structlog()` — deliberate exception to "no shared infra edits"

**Decision**: `apps/api/src/iguanatrader/contexts/observability/structlog_config.py::configure_logging(env: Env)` is the new authoritative entry point. `apps/api/src/iguanatrader/api/app.py::_configure_structlog()` is refactored to a one-liner: `from iguanatrader.contexts.observability.structlog_config import configure_logging; configure_logging(get_env())`. The new function:
- Tests / `IGUANATRADER_ENV=test`: identical to slice-5 — JSON to stdout, no file handler.
- Dev / `IGUANATRADER_ENV=dev`: JSON to stdout + dev pretty-printer when stdout is a TTY.
- Paper / live: JSON to stdout + `RotatingFileHandler` writing to `logs/iguanatrader-{env}.log` with `maxBytes=100*1024*1024` (100MB per NFR-O3) and `backupCount=7` (~7 days retention at typical log volume; precise retention depends on volume — documented as "100MB rotation, retain 7 backups").

This is a deliberate exception to the "slice O1 doesn't edit shared infra" scope clause. Justification: NFR-O3 requires file rotation; the only sensible owner is the observability context; pushing the config there + leaving a one-liner stub in `app.py` is the cleanest factoring. Documented inline in the modified `_configure_structlog()` docstring.

**Alternatives considered**:
- **Leave `_configure_structlog()` in `app.py` and add the file handler there**: spreads observability concerns across two files; future enhancements (OTLP forwarding, log sampling) would add to the wrong file.
- **Wrap stdlib `logging.handlers.RotatingFileHandler` directly in `app.py`**: same problem; the handler config wants to live alongside the rest of the observability primitives.
- **Skip RotatingFileHandler MVP, push to O2**: NFR-O3 is a hard requirement; punt would leave a known compliance gap.

**Rationale**: the bounded-context boundary is more important than the "slice doesn't touch shared file" guideline. Slice 5's `_configure_structlog()` was always a placeholder ("Slice O1 will replace this with a richer config" — verbatim docstring comment in `app.py`). This is the slice doing exactly that.

### D7. OTEL is a port-only stub — `@traced` / `@metered` decorators are no-ops MVP

**Decision**: `otel.py` declares:
- `Tracer` and `Meter` Port classes (Protocol subclasses) per the slice-2 `Port` contract.
- `@traced(span_name)` decorator that, in MVP, just calls the wrapped function (zero overhead — `functools.wraps` only). When v2 SaaS lands the OTEL collector, the decorator body is replaced with `tracer.start_as_current_span(span_name)`.
- `@metered(metric_name, kind)` decorator with the same contract: no-op MVP, real meter v2.
- `init_otel(env)` initializer that, MVP, registers a `NoOpTracer` and `NoOpMeter`. v2 swaps in `OTLPSpanExporter` / `OTLPMetricExporter` configured from env vars.

**Alternatives considered**:
- **Skip OTEL entirely MVP**: leaves a known-future-port-shape ambiguity; downstream slices (R5 brief synthesis with multi-step LLM chains) would benefit from `@traced` on Day 1 even if no exporter is wired yet.
- **Wire real OTEL with stdout exporter MVP**: noisy logs; collector has nowhere to ship to; pure overhead.

**Rationale**: declare the ports now, defer the wiring. Slices that want to instrument heavy operations (R5 multi-step brief synthesis) can use `@traced` from Day 1 — when v2 lands, no caller-side change. The decorator no-op overhead is one function-call indirection; immeasurable.

### D8. `audit_log` per-tenant + cross-tenant — `tenant_id IS NULL` rows for ops-global events

**Decision**: `audit_log` schema (per `migrations/versions/0006_observability_tables.py`):
- `tenant_id UUID NULL` (NOT `NOT NULL` as the rest of per-tenant tables) — NULL means cross-tenant ops-global event (gitleaks pre-commit fail, license-boundary check fail, OTel emission failure, scheduler-level incident).
- `actor_kind TEXT NOT NULL CHECK (actor_kind IN ('user','system','scheduler','channel'))`.
- `event TEXT NOT NULL` — dot-namespaced event name (mirrors MessageBus naming).
- `entity_kind`, `entity_id`, `metadata` per data-model §3.1.
- Indexes: `ix_audit_log_tenant_id_created_at` (NULL-tolerant for global queries), `ix_audit_log_entity_kind_entity_id`.

The `tenant_listener._inject_tenant_filter` MUST handle the NULL-tenant case for `audit_log` queries: when `tenant_id_var` is unset (system context, e.g., scheduler boot) and the query targets `audit_log`, the filter MUST add `WHERE tenant_id IS NULL` (not `WHERE tenant_id = :current` which fails). This is implemented as part of the carry-forward fix to `_inject_tenant_filter` (D9 item a).

**Alternatives considered**:
- **Two separate tables** (`audit_log_per_tenant`, `audit_log_global`): doubles the surface; cross-context queries ("everything that happened in the last hour, regardless of scope") need UNION; rejected.
- **Synthetic `tenant_id = '00000000-0000-0000-0000-000000000000'` for global events**: avoids NULL handling in listener but introduces a magic UUID; rejected per data-model §7.1 wording ("cross-tenant `tenant_id IS NULL` row para ops globales").

**Rationale**: per-tenant + cross-tenant in one table matches the data-model §7.1 contract exactly. The NULL-tolerant index pattern is well-trodden in SQLAlchemy / SQLite.

### D9. Carry-forward items in scope (chosen subset) — rest punted to slice O2

**Decision**: from the 6 retro carry-forward items, slice O1 takes:
- **(a) Fix `_inject_tenant_filter` for non-scoped tables** — directly required by D8 (`audit_log` cross-tenant rows need the listener to handle NULL-tenant queries). Bonus: collapses the slice-4 raw-SQL bypass in `routes/auth.py::login` zero-tenant guard back to ORM (gotcha #28 fix).
- **(b) Boot-time guard rejecting `IGUANATRADER_DEV_INSECURE_COOKIE=1` when `IGUANATRADER_ENV=production`** — security hardening; observability slice is the right home (production-env validation lives next to the env-aware structlog config from D6).
- **(e) `--cov-fail-under=80` in CI pytest invocation** — the slice 5 task 8.3 left this as a TODO with explicit "slice O1 will wire" wording. Direct continuation.
- **(f) Document local poetry-install pattern for Windows venv** — the slice 5 retro flagged "Get poetry install working on Arturo's Windows venv" as O1 follow-up. Documenting the pattern (vs. fixing the underlying poetry issue) is a low-risk doc-only deliverable.

Slice O1 punts to slice O2 (`orchestration-scheduler-routines`):
- **(c) Lint/pre-commit rule flagging ORM SELECT inside `get_current_user`** — defends gotcha #28 contract but is auth-context concern. Slice O2 already wires scheduler entry-point lint rules (lazy-import enforcement per gotcha #29); the ORM-SELECT lint is the same shape (custom ruff rule) and better lands together.
- **(d) Auto-rehash Argon2 on login when stored params drift** — auth-context concern; the login path is owned by slice 4 / future auth-hardening slice; slice O1 has no business touching `routes/auth.py` beyond what D8 + D9(a) require.
- **L2 review marker schema discoverability** — release-management.md concern; not in the observability bounded context; defer to a release-management slice (not O2 either — out-of-band of the slice plan).

**Rationale**: each picked item has a direct logical home in slice O1's surface area (env-aware config, listener, CI / docs). Punted items have a more natural home in slice O2's surface area (scheduler entry-points, login path).

## Risks / Trade-offs

- **[Risk] Cost meter decorator misses callsites** → if a developer calls `anthropic.messages.create(...)` without wrapping in `@cost_meter`, the call is silently un-tracked (cost not persisted, NFR-O1 violated). **Mitigation**: CI integration test introspects `inspect.stack()` to assert SDK calls are inside a `@cost_meter`-decorated stack frame. Documented as gotcha (#31 candidate post-merge). Long-term, a custom `mypy` plugin or ruff rule could flag bare SDK calls.

- **[Risk] In-process Perplexity throttle is process-local** → if MVP grows to multiple worker processes (uvicorn `--workers 4`), each worker has its own window — effective rate is `4 × max_rpm`. **Mitigation**: MVP runs single-process (`--workers 1`); v2 SaaS migration ADR will add Redis-backed throttle. Documented in `docs/architecture-decisions.md` cross-reference + `apps/api/src/iguanatrader/contexts/observability/perplexity_throttle.py` module docstring.

- **[Risk] Budget gate at 100% wedges in-flight routines mid-run** → a routine that started at 95% spend may fire 6 LLM calls before the next budget check; the 4th-6th calls hit BLOCK_100 mid-routine, leaving the routine half-complete. **Mitigation**: routines (slice O2) MUST check budget at routine entry (`check_budget(tenant_id)` returns BLOCK_100 → routine aborts before any LLM spend). The gate is "best effort no-spend-after-block", not "atomic block at the cent".

- **[Risk] Replay cache fixtures drift from real LLM responses** → tests pass against stale fixtures; production behavior diverges. **Mitigation**: `IGUANATRADER_LLM_REPLAY_RECORD=1` mode lets operators refresh fixtures by running the suite against real LLMs (rare; budget-gated; documented procedure in `docs/runbooks/replay-cache-refresh.md` as slice O1 doc deliverable).

- **[Risk] RotatingFileHandler on Windows may fail mid-rotation** (Python's stdlib has known Windows file-locking issues during rotation) → log writes fail silently. **Mitigation**: the handler is wrapped in a try-catch that emits to stderr on rotation failure + reverts to stdout-only. Documented as a v2 follow-up to migrate to a more robust async logger (e.g., `concurrent-log-handler`) once volume justifies it.

- **[Risk] OTEL stub `@traced` decorators accumulate as no-ops; v2 wiring is "just flip a switch" but in practice imports / exporters / collector config are non-trivial** → false sense of v2-readiness. **Mitigation**: design D7 documents the v2 migration path as "swap the decorator body + init_otel() — caller-side unchanged"; ADR-019 (v2 SaaS) will own the actual wiring + integration tests. Slice O1 doesn't claim OTEL is "done", just "ports declared".

- **[Trade-off] `_inject_tenant_filter` carry-forward fix increases listener complexity** — the listener now has 3 cases (scoped table + tenant set, unscoped table + tenant unset, unscoped table + tenant set). Three integration tests cover the matrix; the complexity is worth the gotcha #28 ergonomic fix.

- **[Trade-off] D6 deliberately edits `apps/api/src/iguanatrader/api/app.py`** — this is the first slice-O1+ change to a Wave-0 shared file. The edit is minimal (one-liner delegate) and documented; future slices that want to extend logging (e.g., OTLP forwarding) edit `structlog_config.py`, not `app.py`.

## Migration Plan

This slice has no live deployment to migrate from. Deployment path:

1. Run `alembic upgrade head` on the slice branch — creates `api_cost_events`, `config_changes`, `audit_log`. No data backfill (tables empty until first LLM call).
2. Push slice branch → CI exercises migration on test SQLite + asserts SQLAlchemy listener correctly stamps tenant + rejects UPDATE/DELETE on the new tables.
3. Bot regenerates `packages/shared-types/src/index.ts` with new DTOs (`ApiCostEventDTO`, `BudgetStateDTO`, `CostSnapshotDTO`).
4. Merge to main; subsequent Wave-2+ slices import `@cost_meter`, `route_llm`, `check_budget` and start populating the tables.
5. `IGUANATRADER_DEV_INSECURE_COOKIE=1` boot-time guard fires only when `IGUANATRADER_ENV=production`; existing dev / paper / live setups remain unchanged.

Rollback = revert PR + `alembic downgrade -1` (drops `0006_observability_tables.py` revision). The cost meter / throttle / routing primitives are decorator-based — un-decorating callers is mechanical. Existing slice 5 `_configure_structlog()` is restored from git history if D6 needs reverting.

## Open Questions

- **Q**: Should `BudgetState.WARN_80` auto-downgrade affect ALL subsequent calls in the request lifecycle, or just the next routing decision? **Tentative answer**: just the next call — each `route_llm()` invocation is its own check; if cost crosses 80% mid-request, the next call gets the downgrade. Documented in spec scenario.

- **Q**: Should `audit_log` cross-tenant rows (`tenant_id IS NULL`) have a separate ACL — only operators (system actor) can read them? **Tentative answer**: yes, MVP — `routes/audit.py` (slice O2 territory) will gate `tenant_id IS NULL` queries behind an admin role check. Slice O1 just lands the schema + listener support; query-side ACL is O2.

- **Q**: Default monthly budget cap value (`tenants.feature_flags["llm_budget_usd"]` default $50)? **Tentative answer**: $50/month per tenant MVP — sufficient for ~10K Sonnet calls or 50K Haiku calls; operators raise the cap explicitly via `iguanatrader admin set-budget <tenant> <usd>` (slice O2 CLI). Documented in spec + gotcha #31 candidate.

- **Q**: Replay cache fixture format — JSON with full Anthropic SDK response shape, or simplified `{tokens_input, tokens_output, content}` triple? **Tentative answer**: simplified triple MVP; the production code only consumes those fields from the SDK response; full SDK shape adds noise. If future tests need full SDK behavior (e.g., streaming token emit), revisit.
