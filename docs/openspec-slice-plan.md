---
type: openspec-slice-plan
project: iguanatrader
schema_version: 1
created: 2026-04-28
updated: 2026-04-28
status: gate-c-approved
total_slices: 20
parallel_waves: 4
max_parallel_agents_per_wave: 7
optimization_target: maximum-parallelism-with-disjoint-write-paths
sources:
  - docs/prd.md (76 FRs + 52 NFRs)
  - docs/architecture-decisions.md (Gate A amendment 2026-04-28)
  - docs/data-model.md (29 entities + bitemporal schema)
  - docs/project-structure.md (full monorepo tree)
  - .ai-playbook/specs/runbook-bmad-openspec.md §2.3 (slicing heuristics)
---

# OpenSpec Slice Plan — iguanatrader MVP

Per [`.ai-playbook/specs/runbook-bmad-openspec.md`](../.ai-playbook/specs/runbook-bmad-openspec.md) §3 OpenSpec Implementation: each slice = one `openspec/changes/<slice-id>/` folder with `proposal.md` + `specs/<capability>/spec.md` + `design.md` + `tasks.md`. This document is the canonical source-of-truth for the slice list, dependency graph, and parallelism plan; per-change folders live under `openspec/changes/`.

## Heuristics applied (per runbook §2.3)

- One slice = one bounded context OR one feature within a bounded context
- ≤10 acceptance scenarios per slice (estimated)
- ≤2 directory write_paths per slice (with documented exceptions)
- ≤6 words per slice name
- **Parallelism optimization (Gate C addition)**: write_paths between slices in same wave MUST be disjoint to enable parallel agents in worktrees without merge collision

## Dependency graph

```
Wave 0 — SEQUENTIAL FOUNDATION (must land in order; blocks all downstream)

   1. bootstrap-monorepo
        ↓
   2. shared-primitives
        ↓
   3. persistence-tenant-enforcement

Wave 1 — PARALLEL ×2 (after Wave 0)

   4. auth-jwt-cookie  ║  5. api-foundation-rfc7807

Wave 2 — PARALLEL ×6 (after Wave 1; one slice per bounded context + frontend)

   R1. research-bitemporal-schema
   T1. trading-models-interfaces
   K1. risk-engine-protections
   P1. approval-channels-multichannel
   O1. observability-cost-meter
   W1. dashboard-svelte-skeleton

Wave 3 — PARALLEL ×7 (each branch reads only Wave 2 outputs; mocks for cross-track)

   R2. research-edgar-fred-adapters       (after R1)
   R3. research-news-catalysts-adapters   (after R1)
   R4. openbb-sidecar-container           (after Wave 0; can start anywhere ≥Wave 1)
   R5. research-brief-synthesis           (after R1; mocks R2-R4 sources during dev)
   T2. ibkr-adapter-resilient             (after T1)
   T3. donchian-strategy-mvp              (after T1)
   O2. orchestration-scheduler-routines   (after O1)

Wave 4 — PARALLEL ×2 (consolidation)

   R6. hindsight-integration              (after R5)
   T4. trading-routes-and-daemon          (after T1+T2+T3)
```

## Slice catalogue

### Wave 0 — Sequential foundation

| # | Slice ID | Depends on | Write paths principales | FR/NFR refs |
|---|---|---|---|---|
| 1 | `bootstrap-monorepo` | — | repo root (pyproject.toml, pnpm-workspace.yaml, Makefile + Makefile.includes pattern, docker-compose{,.paper,.live,.test}.yml + litestream service, .github/workflows/{ci,build-images,openapi-types,license-boundary-check}.yml, .pre-commit-config.yaml, .gitignore, .gitleaksignore, .editorconfig, .secrets/.sops.yaml + dev.env.enc template, AGENTS.md/CLAUDE.md routers, LICENSE, SECURITY.md, CONTRIBUTING.md, CHANGELOG.md, README.md) | NFR-S1, NFR-S2, NFR-M9 |
| 2 | `shared-primitives` | 1 | `apps/api/src/iguanatrader/shared/{messagebus,kernel,types,contextvars,errors,time,decimal_utils,heartbeat,backoff,ports}.py` + `apps/api/tests/property/{test_message_ordering,test_decimal_arithmetic,test_heartbeat_idempotency,test_backoff_monotonicity}.py` | NFR-P8, NFR-R7, NFR-I2, NFR-I5, NFR-O2 |
| 3 | `persistence-tenant-enforcement` | 2 | `apps/api/src/iguanatrader/persistence/{session,tenant_listener,append_only_listener,base}.py` + `apps/api/src/iguanatrader/migrations/env.py` + `migrations/versions/0001_initial_schema.py` (mutable tables: tenants, users, authorized_senders) + JSON1 verify on boot in `main.py` lifespan | NFR-SC1, NFR-SC2, FR46-FR49 |

### Wave 1 — Parallel ×2

| # | Slice ID | Depends on | Write paths | FR/NFR refs |
|---|---|---|---|---|
| 4 | `auth-jwt-cookie` | 3 | `apps/api/src/iguanatrader/api/{auth,deps}.py` + `api/routes/auth.py` + `api/dtos/auth.py` + `apps/api/tests/integration/test_auth_flow.py` + Argon2id setup | NFR-S3-S5, FR31, FR38 |
| 5 | `api-foundation-rfc7807` | 3 | `apps/api/src/iguanatrader/api/{app,errors}.py` + `api/dtos/common.py` + `api/routes/__init__.py` (**dynamic discovery via pkgutil — anti-collision pattern**) + `api/sse/__init__.py` (dynamic) + `cli/main.py` (typer auto-discovery) + `packages/shared-types/{package.json,tsconfig.json,src/index.ts}` + openapi-typescript pipeline script + Lighthouse CI step | NFR-P7, NFR-O8 |

### Wave 2 — Parallel ×6 (one per bounded context + frontend)

| # | Slice ID | Depends on | Write paths | FR/NFR refs |
|---|---|---|---|---|
| R1 | `research-bitemporal-schema` | 5 | `contexts/research/{__init__,models,ports,repository,events}.py` + `migrations/versions/0002_research_tables.py` (research_sources cross-tenant, symbol_universe, watchlist_configs, research_facts bitemporal con CHECK provenance + hybrid raw_payload, research_briefs versioned, corporate_events, analyst_ratings) + `api/dtos/research.py` (stubs) + `api/routes/research.py` (stubs) + `tests/unit/contexts/research/{test_bitemporal_queries,test_provenance_enforcement}.py` | FR68-FR70, FR73, NFR-O8 |
| T1 | `trading-models-interfaces` | 5 | `contexts/trading/{__init__,models,ports,service,repository,events}.py` + `migrations/versions/0003_trading_tables.py` (strategy_configs, trade_proposals con research_brief_id FK, trades, orders, fills, equity_snapshots) + `api/dtos/{trades,proposals}.py` | FR1-FR5, FR11, FR14, FR46 |
| K1 | `risk-engine-protections` | 5 | `contexts/risk/*` completo (engine pure-fn + protections/{per_trade,daily,weekly,max_open,max_drawdown}.py + service + repository + events) + `migrations/versions/0004_risk_tables.py` (risk_evaluations, risk_overrides, kill_switch_state, kill_switch_events) + `api/routes/risk.py` + `api/sse/risk.py` + `cli/ops.py` (halt/resume/override) + `tests/property/test_risk_caps_invariant.py` (CI-blocking) | FR19-FR30, NFR-R5, NFR-R6 |
| P1 | `approval-channels-multichannel` | 5 | `contexts/approval/*` (channels/{telegram,whatsapp_hermes,command_handler}.py + service + repository + events) + 17 commands shared + `migrations/versions/0005_approval_tables.py` (approval_requests, approval_decisions) + `api/routes/approvals.py` + `api/sse/approvals.py` + `tests/integration/{test_telegram_resilience,test_hermes_resilience}.py` | FR12, FR13, FR31-FR38, NFR-I5, NFR-I6 |
| O1 | `observability-cost-meter` | 5 | `contexts/observability/*` (cost_meter, perplexity_throttle, llm_routing, budget, replay_cache, cost_dashboard_publisher, structlog_config con RotatingFileHandler 100MB/7d, otel, models, repository) + `migrations/versions/0006_observability_tables.py` (api_cost_events, config_changes, audit_log) + `api/routes/costs.py` + `api/sse/costs.py` + `tests/integration/test_perplexity_throttle.py` | FR39-FR42, NFR-O1, NFR-O3, NFR-O4, NFR-O7, NFR-I3, NFR-I4 |
| W1 | `dashboard-svelte-skeleton` | 4, 5 | `apps/web/*` completo (auth pages, layout authenticated, +error.svelte, components base + nav/Sidebar.svelte con **dynamic enumeration via import.meta.glob**, stores base, composables base, /sse consumers stubs, Lighthouse config, Playwright config) — domain pages renderean "loading..." hasta que cada track aterrice sus endpoints | FR54, FR55, NFR-P7 |

### Wave 3 — Parallel ×7

| # | Slice ID | Depends on | Write paths | FR/NFR refs |
|---|---|---|---|---|
| R2 | `research-edgar-fred-adapters` | R1 | `contexts/research/sources/{sec_edgar,fred,bls,bea}.py` + `tests/integration/{test_edgar_ingestion,test_fred_ingestion}.py` | FR59, FR60 |
| R3 | `research-news-catalysts-adapters` | R1 | `contexts/research/sources/{finnhub,gdelt,openfda,openinsider,finviz_scrape,wgi_world_bank,vdem,ibkr_bars,yahoo_bars_fallback}.py` + `contexts/research/scraping/*` (4-tier ladder: tier1_webfetch, tier2_playwright, tier3_camoufox, tier4_captcha + robots_check + user_agent) + `tests/integration/test_news_ingestion.py` + `tests/unit/contexts/research/test_scrape_ladder.py` | FR61-FR67, FR77-FR79 |
| R4 | `openbb-sidecar-container` | 1 | `apps/openbb-sidecar/*` (Dockerfile + pyproject AGPL + LICENSE separate + src/openbb_sidecar/{main,config,routes/{health,equity,economy},adapters/openbb_facade}.py) + `contexts/research/sources/{openbb_sidecar,yfinance_proxy}.py` (HTTP client) + `.github/workflows/license-boundary-check.yml` enforcement | FR76, ADR-015 |
| R5 | `research-brief-synthesis` | R1 | `contexts/research/{service,scheduler}.py` + `synthesis/*` (synthesizer + citation_resolver + audit_trail + prompts/{three_pillar,canslim,magic_formula,qarp,multi_factor}.md) + `methodology/*` (5 frameworks) + `feature_provider/*` (tier_a, tier_b, tier_c) + `api/routes/research.py` (full impl) + `api/sse/research.py` + `cli/research.py` + `web/src/routes/(app)/research/[symbol]/{+page,audit-trail/[brief_version]/+page}.svelte` + `web/src/lib/components/research/{BriefHeader,FactTimeline,CitationLink,AuditTrailViewer,MethodologyBadge}.svelte` + `tests/integration/test_research_brief_refresh.py` + `tests/unit/contexts/research/{test_audit_trail_render,test_methodology_profiles,test_feature_provider_tier,test_citation_resolver}.py` | FR58, FR71-FR75, NFR-P9, NFR-O8 |
| T2 | `ibkr-adapter-resilient` | T1 | `contexts/trading/brokers/{ibkr_adapter,ibkr_brokerage_model}.py` (HeartbeatMixin + backoff [3,6,12,24,48]) + `tests/integration/{test_ibkr_resilience,test_reconciliation}.py` | FR14-FR16, NFR-R2, NFR-R7, NFR-I1, NFR-I2, NFR-P8 |
| T3 | `donchian-strategy-mvp` | T1 | `contexts/trading/strategies/{base,donchian_atr,sma_cross,manager}.py` + `tests/property/test_strategy_no_lookahead.py` + `config/strategies.yaml` template | FR1-FR5, FR11 |
| O2 | `orchestration-scheduler-routines` | O1 | `contexts/orchestration/*` (service + scheduler APScheduler + alert_filter + tier1_alerts + nodes/{premarket,midday,postmarket,weekly_review}.py + report_pdf.py + prompts/*) + `migrations/versions/0007_orchestration_tables.py` (routine_runs, alert_events) + `api/sse/alerts.py` + `tests/integration/test_orchestration.py` | FR33-FR35, FR43, FR44, NFR-P3, NFR-P4 |

### Wave 4 — Parallel ×2

| # | Slice ID | Depends on | Write paths | FR/NFR refs |
|---|---|---|---|---|
| R6 | `hindsight-integration` | R5 | `contexts/research/sources/{hindsight_recall,hindsight_retain}.py` + `migrations/versions/0008_tenants_feature_flags.py` (ALTER TABLE tenants ADD COLUMN feature_flags JSONB DEFAULT '{}') + `api/routes/settings.py` + `cli/settings.py` + `web/src/routes/(app)/settings/{+page.svelte,+page.server.ts}` + `tests/integration/{test_hindsight_recall_gated,test_hindsight_retain_always_on}.py` | FR51, FR80, FR81, NFR-I8 |
| T4 | `trading-routes-and-daemon` | T1, T2, T3 | `api/routes/{trades,portfolio,strategies}.py` (full impl) + `api/sse/equity.py` + `cli/{paper,live,propose,export,strategies}.py` + `web/src/routes/(app)/{trades,portfolio,strategies}/*` + `tests/integration/test_proposal_to_fill_flow.py` + `tests/integration/test_kill_switch_flow.py` + `tests/integration/test_cross_tenant_isolation.py` | FR12-FR18, FR50, FR52-FR56 |

## Anti-collision patterns (established in slice 5)

These patterns prevent multi-slice merge conflicts on shared registry/index files:

| Pattern | Location | Mechanism |
|---|---|---|
| **API routes auto-discovery** | `apps/api/src/iguanatrader/api/routes/__init__.py` | `for module in pkgutil.iter_modules(__path__): app.include_router(module.router)`. Each slice only adds `routes/<name>.py`; init.py never edited. |
| **API SSE auto-discovery** | `apps/api/src/iguanatrader/api/sse/__init__.py` | Same pattern. |
| **CLI typer auto-discovery** | `apps/api/src/iguanatrader/cli/main.py` | `for cmd_module in pkgutil.iter_modules(...): app.add_typer(cmd_module.app, name=...)`. Each slice adds `cli/<name>.py`. |
| **Frontend sidebar dynamic enumeration** | `apps/web/src/lib/components/nav/Sidebar.svelte` | `import.meta.glob('/src/routes/(app)/*/+page.svelte')` lists routes at compile time; sidebar renders dynamically. |
| **Frontend api lib re-exports** | `apps/web/src/lib/api/index.ts` | Pre-commit hook regenerates from `lib/api/*.ts` glob. |
| **Alembic migrations** | `apps/api/src/iguanatrader/migrations/versions/` | Each slice writes `000N_<slice>.py` with monotonic N. CI validates no gaps. |
| **Makefile** | `Makefile` (root) + `Makefile.includes` per slice | Root includes via `include apps/api/Makefile.includes` + `include apps/web/Makefile.includes`. Each slice owns its `.includes` file. |

## Workflow per slice

1. **Branch + worktree**: `git worktree add ../iguana-<slice-id> -b slice/<slice-id> main`
2. **Agent assignment**: parallel agent invoked with `isolation: "worktree"` to isolated workspace
3. **OpenSpec lifecycle** (per `.ai-playbook/specs/runbook-bmad-openspec.md` §3.1):
   - `/opsx:propose <slice-id>` → generates `openspec/changes/<slice-id>/{proposal.md, specs/<capability>/spec.md, design.md, tasks.md}`
   - Per-artefact worker → QA → verdict (max 2 rework per finding); iter 3 same finding ⇒ `❓ blocked-by-spec`
   - `/opsx:apply <slice-id>` → implementation + tests in branch
   - `/opsx:archive <slice-id>` → promotes specs to `openspec/specs/`, retro at `retros/<slice-id>.md`
4. **CI gates** in branch: lint + type-check + test + secrets scan + license-boundary-check + lighthouse-perf
5. **PR to main**: human reviewer (Gate F equivalent) approves via GitHub + records in `docs/hitl-gates-log.md`
6. **Squash-merge**: branch deleted post-merge; worktree torn down

## Per-slice acceptance criteria template

Each slice's `tasks.md` (generated by `/opsx:propose`) MUST include:

- [ ] All write_paths listed in this slice's row are touched and ONLY those (no scope creep)
- [ ] DB migration (if any) numbered correctly + reversible (`down_revision` set)
- [ ] Unit tests for new code at coverage ≥80% (per NFR-M1)
- [ ] Integration test for E2E flow (where applicable)
- [ ] Property test for invariants (where applicable, e.g. RiskEngine, HeartbeatMixin, no_lookahead)
- [ ] Documentation: append to `docs/gotchas.md` if any non-obvious lessons emerged (NFR-M7)
- [ ] No new external deps without `pyproject.toml` / `package.json` justification + license check
- [ ] No cross-context deep imports (only via `__init__.py` public API or MessageBus events) — ruff custom rule enforces
- [ ] structlog event names follow `<context>.<entity>.<action>` pattern
- [ ] All dates ISO 8601 UTC (per memory feedback)
- [ ] Pre-commit passes (gitleaks + ruff + black + mypy strict + eslint + prettier + openapi-typescript regen)

## Cross-references

- [docs/prd.md](prd.md) — source FRs/NFRs each slice realizes
- [docs/architecture-decisions.md](architecture-decisions.md) — bounded context boundaries each slice respects
- [docs/data-model.md](data-model.md) — entity definitions referenced in `models.py` per slice
- [docs/project-structure.md](project-structure.md) — full file layout each slice's write_paths reference
- [docs/hitl-gates-log.md](hitl-gates-log.md) — Gate C approval recording this plan
- [.ai-playbook/specs/runbook-bmad-openspec.md](../.ai-playbook/specs/runbook-bmad-openspec.md) §3 — OpenSpec lifecycle each slice follows
