---
title: iguanatrader MVP — OpenSpec slicing
date: 2026-04-28
approver: Arturo Ramírez (arturo6ramirez@gmail.com)
prereq_gates:
  - Gate A — 2026-04-28 (PRD sealed + Research domain amendment)
  - Gate B — 2026-04-28 (Architecture + data model + project structure + Hindsight integration)
status: approved
runbook: .ai-playbook/specs/runbook-bmad-openspec.md §2.4
optimization_target: maximum-parallelism-with-disjoint-write-paths
total_changes: 20
parallel_waves: 4
max_parallel_agents_per_wave: 7
sources:
  - docs/prd.md (76 FRs + 52 NFRs)
  - docs/architecture-decisions.md (Gate A amendment 2026-04-28)
  - docs/data-model.md (29 entities + bitemporal schema)
  - docs/project-structure.md (full monorepo tree)
  - .ai-playbook/specs/bmad-openspec-bridge.md §3.1 (canonical schema)
  - .ai-playbook/specs/runbook-bmad-openspec.md §2.4 (slicing) + §3.1 (per-change sequence)
---

# iguanatrader MVP — OpenSpec slicing

The iguanatrader MVP — algorithmic trading bot, paper-first → live IBKR — was sliced into **20 OpenSpec changes** organised as 4 parallel waves with disjoint write paths to enable up to 7 concurrent agents per wave (worktree-isolated). Every FR (FR1-FR81, 76 total) and NFR (NFR-P1..NFR-O8, 52 total) traces to ≥1 change. Wave 0 is sequential foundation (3 changes); Waves 1-4 are parallel-safe via dynamic-discovery anti-collision patterns established in change `api-foundation-rfc7807`.

## Approved change list

| #  | Change ID                          | Bounded context | FRs                              | Journeys (if UI)        | Components (if UI)                                          | Depends on |
|----|------------------------------------|------------------|----------------------------------|-------------------------|-------------------------------------------------------------|------------|
| 1  | `bootstrap-monorepo`               | shared kernel   | (foundation: NFR-S1, NFR-S2, NFR-M9) | —                   | —                                                           | —          |
| 2  | `shared-primitives`                | shared kernel   | (foundation: NFR-P8, NFR-R7, NFR-I2, NFR-I5, NFR-O2) | —    | —                                                           | `bootstrap-monorepo` |
| 3  | `persistence-tenant-enforcement`   | shared kernel   | FR46-FR49 (+NFR-SC1, NFR-SC2)    | (infra)                 | —                                                           | `shared-primitives` |
| 4  | `auth-jwt-cookie`                  | shared kernel   | FR31, FR38 (+NFR-S3-S5)          | J1 (login surface)      | —                                                           | `persistence-tenant-enforcement` |
| 5  | `api-foundation-rfc7807`           | shared kernel   | (foundation: NFR-P7, NFR-O8)     | (infra)                 | —                                                           | `persistence-tenant-enforcement` |
| R1 | `research-bitemporal-schema`       | research        | FR68-FR70, FR73 (+NFR-O8)        | (infra)                 | —                                                           | `api-foundation-rfc7807` |
| T1 | `trading-models-interfaces`        | trading         | FR1-FR5, FR11, FR14, FR46        | (infra)                 | —                                                           | `api-foundation-rfc7807` |
| K1 | `risk-engine-protections`          | risk            | FR19-FR30 (+NFR-R5, NFR-R6)      | (infra)                 | —                                                           | `api-foundation-rfc7807` |
| P1 | `approval-channels-multichannel`   | approval        | FR12, FR13, FR31-FR38 (+NFR-I5, NFR-I6) | J2 (approval flow) | —                                                           | `api-foundation-rfc7807` |
| O1 | `observability-cost-meter`         | observability   | FR39-FR42 (+NFR-O1, NFR-O3, NFR-O4, NFR-O7, NFR-I3, NFR-I4) | (infra) | —                                                       | `api-foundation-rfc7807` |
| W1 | `dashboard-svelte-skeleton`        | shared kernel (UI) | FR54, FR55 (+NFR-P7)          | J1 (skeleton), J2 (skeleton) | Sidebar (dynamic), base layout, +error.svelte         | `auth-jwt-cookie`, `api-foundation-rfc7807` |
| R2 | `research-edgar-fred-adapters`     | research        | FR59, FR60                       | (infra)                 | —                                                           | `research-bitemporal-schema` |
| R3 | `research-news-catalysts-adapters` | research        | FR61-FR67, FR77-FR79             | (infra)                 | —                                                           | `research-bitemporal-schema` |
| R4 | `openbb-sidecar-container`         | research        | FR76 (ADR-015)                   | (infra)                 | —                                                           | `bootstrap-monorepo` |
| R5 | `research-brief-synthesis`         | research        | FR58, FR71-FR75 (+NFR-P9, NFR-O8) | J3 (briefings)         | BriefHeader, FactTimeline, CitationLink, AuditTrailViewer, MethodologyBadge | `research-bitemporal-schema` (mocks R2-R4) |
| T2 | `ibkr-adapter-resilient`           | trading         | FR14-FR16 (+NFR-R2, NFR-R7, NFR-I1, NFR-I2, NFR-P8) | (infra) | —                                                       | `trading-models-interfaces` |
| T3 | `donchian-strategy-mvp`            | trading         | FR1-FR5, FR11                    | (infra)                 | —                                                           | `trading-models-interfaces` |
| O2 | `orchestration-scheduler-routines` | orchestration   | FR33-FR35, FR43, FR44 (+NFR-P3, NFR-P4) | (infra)         | —                                                           | `observability-cost-meter` |
| R6 | `hindsight-integration`            | research        | FR51, FR80, FR81 (+NFR-I8)       | Settings (UI toggle)    | Settings page (feature_flags toggle)                        | `research-brief-synthesis` |
| T4 | `trading-routes-and-daemon`        | trading         | FR12-FR18, FR50, FR52-FR56       | J1 (portfolio/trades), J2 (proposals) | trades/portfolio/strategies routes (no new named components) | `trading-models-interfaces`, `ibkr-adapter-resilient`, `donchian-strategy-mvp` |

## Scope notes

### 1. `bootstrap-monorepo`

Establece el monorepo skeleton + tooling baseline que las otras 19 slices consumen. Touchpoints: `pyproject.toml` (Poetry workspace root con dev tooling shared: ruff/black/mypy strict/pytest), `pnpm-workspace.yaml` (declara `apps/web` + `packages/shared-types`), Makefile root + Makefile.includes pattern, `docker-compose{,.paper,.live,.test}.yml` (con litestream service para SQLite continuous backup), 4 GitHub workflows (`ci.yml`, `build-images.yml`, `openapi-types.yml`, `license-boundary-check.yml`), `.pre-commit-config.yaml` (gitleaks + ruff + black + mypy + check-toml + eslint stub + prettier stub + openapi-typescript regen + license-boundary check), `.gitignore`, `.gitleaksignore`, `.editorconfig`, `.dockerignore`, `.secrets/.sops.yaml` (age recipients) + `dev.env.enc`/`paper.env.enc`/`live.env.enc` template stubs, LICENSE (Apache-2.0 + Commons Clause v1.0 verbatim), SECURITY.md, CONTRIBUTING.md placeholder, CHANGELOG.md initial entry, README.md, THIRD_PARTY_NOTICES.md placeholder, `docs/getting-started.md` (prereqs incl. JSON1 SQLite smoke test, install steps, paper-trading walkthrough placeholder), 4 ADR drafts authored as físicos archivos en `docs/adr/` (ADR-014 bitemporal-research-facts, ADR-015 openbb-sidecar-isolation, ADR-016 research-domain-and-backtest-skip, ADR-017 scrape-ladder-4-tiers). Out of scope: cualquier código fuente en `apps/api/src/` o `apps/web/src/` (slices 2 y W1 los plantan), `apps/openbb-sidecar/` (slice R4), DB migrations (slice 3 planta la primera). Acceptance crítica: `make bootstrap` corre limpio; `pre-commit run --all-files` pasa; `docker compose config` valida los 4 archivos; LICENSE checksumeado contra fuente canónica Apache-2.0; los 4 ADRs existen con skeleton + status proposed.

### 2. `shared-primitives`

Aterriza el "shared kernel" del DDD: primitivos puros sin dependencias hacia bounded contexts, consumidos por TODOS los contextos posteriores. Touchpoints: `apps/api/src/iguanatrader/shared/{messagebus,kernel,types,contextvars,errors,time,decimal_utils,heartbeat,backoff,ports}.py`. Components clave: `MessageBus` con orden FIFO garantizado por subscriber + idempotencia opcional (NFR-O2); `BaseRepository` con session injection vía `contextvars` (NFR-SC1); `Decimal`-based money type (no float); `HeartbeatMixin` para adapters live (NFR-P8/R7/I2/I5) — interfaz que `IBKRAdapter`, `TelegramChannel`, `HermesChannel` heredarán sin reimplementar; helper de backoff exponencial `[3, 6, 12, 24, 48]` segundos canonical (NFR-R7); error hierarchy + RFC 7807 Problem Details base. Tests property-based en `apps/api/tests/property/`: `test_message_ordering`, `test_decimal_arithmetic` (no precisión perdida), `test_heartbeat_idempotency`, `test_backoff_monotonicity`. Out of scope: cualquier referencia a contextos concretos; este módulo NO conoce trading, research, risk, etc. — es kernel puro.

### 3. `persistence-tenant-enforcement`

Aterriza la infraestructura de persistencia con tenant-isolation desde la primera migración. Touchpoints: `apps/api/src/iguanatrader/persistence/{session,tenant_listener,append_only_listener,base}.py` + `apps/api/src/iguanatrader/migrations/env.py` (Alembic env config con autogenerate respetando `naming_convention`) + `migrations/versions/0001_initial_schema.py` (las únicas tablas mutables de toda la app: `tenants` con `feature_flags JSONB`, `users`, `authorized_senders`). Components clave: SQLAlchemy event listener `tenant_listener` que inyecta `tenant_id` en todas las queries vía `contextvars` (NFR-SC1); `append_only_listener` que rechaza `UPDATE`/`DELETE` sobre tablas marcadas `__tablename_is_append_only__` (NFR-SC2 + ADR sobre append-only event sourcing); JSON1 SQLite verify on boot en `main.py` lifespan (rechaza arrancar si JSON1 missing); naming convention para constraints (FK/UQ/IX) que estabiliza autogenerate diffs. Tests integration: cross-tenant read attempt → empty result; UPDATE sobre append-only table → IntegrityError; JSON1 missing → boot fails con mensaje explícito.

### 4. `auth-jwt-cookie`

Auth flow JWT-cookie httponly+samesite=strict + Argon2id password hashing, single-tenant first user → admin, second tenant via CLI bootstrap. Touchpoints: `apps/api/src/iguanatrader/api/{auth,deps}.py` (JWT encode/decode + dependency `get_current_user` que carga tenant a `contextvars`) + `api/routes/auth.py` (login/logout/refresh/me) + `api/dtos/auth.py` (LoginRequest, LoginResponse) + `apps/api/tests/integration/test_auth_flow.py` (login → cookie → /me → logout). El primer user de un tenant es admin automáticamente; tenants adicionales se crean vía CLI `iguanatrader admin create-tenant <slug>` (out of scope, en T4). Argon2id con parámetros sane defaults documentados en gotchas. Cookie samesite=strict + secure (en prod) + httponly. JWT expira 24h; refresh con rotación.

### 5. `api-foundation-rfc7807`

Aterriza el "API foundation" pattern: RFC 7807 Problem Details para todos los errores + dynamic-discovery patterns que TODAS las slices posteriores explotan para evitar merge collisions. Touchpoints: `apps/api/src/iguanatrader/api/{app,errors}.py` (FastAPI app factory + global exception handler que mappea `IguanaError` hierarchy a RFC 7807 JSON) + `api/dtos/common.py` (Problem, ErrorDetail) + `api/routes/__init__.py` (**dynamic discovery via `pkgutil.iter_modules` — anti-collision pattern crítico**: cada slice añade `routes/<name>.py` y nadie edita `__init__.py`) + `api/sse/__init__.py` (mismo patrón para SSE endpoints) + `cli/main.py` (typer app con auto-discovery de subcommands en `cli/`) + `packages/shared-types/{package.json, tsconfig.json, src/index.ts}` (TypeScript paquete generado vía `openapi-typescript` desde `/openapi.json`) + script de pipeline en `.github/workflows/openapi-types.yml` que regenera `packages/shared-types/src/index.ts` en pre-commit + Lighthouse CI step. Out of scope: cualquier ruta concreta (auth en slice 4, cada contexto en su slice); este planta la fundación que evita choques.

### R1. `research-bitemporal-schema`

Bounded context "research" — schema bitemporal para FACTS con provenance enforcement + tablas auxiliares de catálogo. Touchpoints: `contexts/research/{__init__,models,ports,repository,events}.py` + `migrations/versions/0002_research_tables.py` (7 tablas: `research_sources` cross-tenant, `symbol_universe`, `watchlist_configs` per-tenant, `research_facts` con bitemporal `effective_from/to × recorded_from/to` + CHECK constraint enforcing provenance + hybrid `raw_payload_inline`/`raw_payload_path`/`raw_payload_sha256`/`raw_payload_size_bytes` para payloads ≥16KB on filesystem, `research_briefs` versioned, `corporate_events`, `analyst_ratings`) + `api/dtos/research.py` (stubs de DTOs leídos por R5) + `api/routes/research.py` (stubs que devuelven 501 hasta R5) + tests `tests/unit/contexts/research/{test_bitemporal_queries,test_provenance_enforcement}.py`. Esta slice deja el modelo + stubs; R2/R3/R4/R5 plantarán adapters + síntesis por encima.

### T1. `trading-models-interfaces`

Bounded context "trading" — entities + ports + interfaces sin aterrizar adapters concretos (T2 IBKR + T3 Donchian se plantan después en paralelo). Touchpoints: `contexts/trading/{__init__,models,ports,service,repository,events}.py` + `migrations/versions/0003_trading_tables.py` (`strategy_configs`, `trade_proposals` con FK a `research_briefs.id`, `trades`, `orders`, `fills`, `equity_snapshots`) + `api/dtos/{trades,proposals}.py`. `ports.py` define `BrokerPort` (interfaz que IBKR adapter implementa en T2) + `StrategyPort` (que Donchian implementa en T3). `service.py` orquesta: `propose → risk_check → enqueue_approval → execute_on_approval → reconcile_fills`. `events.py` declara los eventos del bus que cruzan al risk/approval/observability contexts.

### K1. `risk-engine-protections`

Bounded context "risk" completo — engine pure-functional + 5 protections + servicio + repositorio + eventos + kill switch. Touchpoints: `contexts/risk/*` completo (`engine.py` pure-fn que toma `Proposal + State → Decision`; `protections/{per_trade,daily,weekly,max_open,max_drawdown}.py`; `service.py` orquestador; `repository.py`; `events.py`) + `migrations/versions/0004_risk_tables.py` (`risk_evaluations`, `risk_overrides` con audit, `kill_switch_state`, `kill_switch_events` append-only) + `api/routes/risk.py` (GET state, POST override) + `api/sse/risk.py` (events stream) + `cli/ops.py` (`halt`, `resume`, `override` commands) + `tests/property/test_risk_caps_invariant.py` **CI-blocking** (Hypothesis verifica que ninguna combinación de proposals viola los caps 2/5/15 — NFR-R5/R6). Caps por defecto: 2% per-trade, 5% daily, 15% max-drawdown (override admin con audit; recorded_by + reason mandatorios).

### P1. `approval-channels-multichannel`

Bounded context "approval" completo — 17 commands shared entre Telegram + Hermes/WhatsApp con resilience (HeartbeatMixin + backoff). Touchpoints: `contexts/approval/*` (`channels/{telegram,whatsapp_hermes,command_handler}.py` + `service.py` + `repository.py` + `events.py`) + 17 commands shared (`/approve`, `/reject`, `/halt`, `/resume`, `/status`, `/positions`, `/equity`, `/strategies`, `/risk`, `/override`, `/cost`, `/budget`, `/help`, `/whoami`, `/lock`, `/unlock`, `/logout`) + `migrations/versions/0005_approval_tables.py` (`approval_requests`, `approval_decisions` append-only) + `api/routes/approvals.py` + `api/sse/approvals.py` + tests `tests/integration/{test_telegram_resilience,test_hermes_resilience}.py` (heartbeat reconnect after channel drop). Cada channel hereda `HeartbeatMixin` de slice 2 + backoff canonical `[3, 6, 12, 24, 48]`.

### O1. `observability-cost-meter`

Bounded context "observability" completo — cost meter para LLM calls + Perplexity rate-throttle + LLM routing decision + budget gates + replay cache + cost dashboard publisher + structlog config + OTEL stub. Touchpoints: `contexts/observability/*` (`cost_meter.py`, `perplexity_throttle.py` con sliding window, `llm_routing.py` (dec entre Claude/Sonnet/Haiku/GPT por task class), `budget.py` (per-tenant monthly cap), `replay_cache.py` (deterministic LLM replay para tests), `cost_dashboard_publisher.py`, `structlog_config.py` con `RotatingFileHandler` 100MB/7d (NFR-O3), `otel.py` stub, `models.py`, `repository.py`) + `migrations/versions/0006_observability_tables.py` (`api_cost_events` per-call, `config_changes` append-only, `audit_log` append-only scoped per-tenant) + `api/routes/costs.py` + `api/sse/costs.py` + tests `tests/integration/test_perplexity_throttle.py`. Audit log scope decision (data-model §7): per-tenant + cross-tenant `tenant_id IS NULL` row para ops globales.

### W1. `dashboard-svelte-skeleton`

Aterriza `apps/web/*` completo como skeleton — login pages, layout authenticated, error.svelte, components base, **Sidebar.svelte con dynamic enumeration via `import.meta.glob('/src/routes/(app)/*/+page.svelte')` — anti-collision pattern crítico** (cada slice posterior añade su ruta y la sidebar la recoge automáticamente sin merge), stores base, composables base, `/sse` consumers stubs, Lighthouse config target ≥90 perf/best-practices, Playwright config E2E. Domain pages (research, trades, portfolio, strategies, settings, costs, risk, approvals) renderean `"loading…"` placeholder hasta que cada track aterrice sus endpoints en sus slices respectivas. Out of scope: contenido de cada domain page (cada slice posterior planta el suyo).

### R2. `research-edgar-fred-adapters`

Adapters de fuentes Tier-A (native point-in-time) — SEC EDGAR (Form 4 insider, 10-K, 10-Q, 8-K), FRED (macro indicators), BLS (employment), BEA (GDP). Touchpoints: `contexts/research/sources/{sec_edgar,fred,bls,bea}.py` + tests `tests/integration/{test_edgar_ingestion,test_fred_ingestion}.py`. Cada adapter implementa el `SourcePort` definido en R1 + persiste a `research_facts` con `tier='A'` + `effective_from/to` populated from source PiT. Sin scraping (todos APIs públicas con rate limits sane). Idempotencia: `research_sources.dedupe_key` previene re-ingesta del mismo filing.

### R3. `research-news-catalysts-adapters`

Adapters de fuentes Tier-B (snapshot collected) + Tier-C (bootstrap) — Finnhub news, GDELT events, OpenFDA approvals, OpenInsider scraping, Finviz screener scraping, World Bank WGI governance, V-Dem democracy index, IBKR historical bars, Yahoo Finance bars fallback. Touchpoints: `contexts/research/sources/{finnhub,gdelt,openfda,openinsider,finviz_scrape,wgi_world_bank,vdem,ibkr_bars,yahoo_bars_fallback}.py` + `contexts/research/scraping/*` (4-tier ladder: `tier1_webfetch.py` → `tier2_playwright.py` → `tier3_camoufox.py` → `tier4_captcha.py` con paid solver opcional + `robots_check.py` + `user_agent.py` rotation) + tests `tests/integration/test_news_ingestion.py` + `tests/unit/contexts/research/test_scrape_ladder.py`. ESG via yfinance.sustainability included como best-effort single-source (CI assertion: prohibido en backtest features per FR75).

### R4. `openbb-sidecar-container`

Container separado para OpenBB SDK con AGPL-3.0 boundary preservado vía HTTP-loopback isolation. Touchpoints: `apps/openbb-sidecar/*` (Dockerfile + `pyproject.toml` AGPL declarado + LICENSE separate + `src/openbb_sidecar/{main,config,routes/{health,equity,economy},adapters/openbb_facade}.py`) + `contexts/research/sources/{openbb_sidecar,yfinance_proxy}.py` (HTTP client desde el monolito Apache+CC al sidecar AGPL) + `.github/workflows/license-boundary-check.yml` enforcement (validates no AGPL deps in `apps/api/`). Sidecar runs en docker-compose service separado con health check; el monolito habla solo HTTP localhost — sin imports de Python al código AGPL. ADR-015 documenta la separación.

### R5. `research-brief-synthesis`

Capa de síntesis sobre R1-R4: 5 metodologías (3-pillar, CANSLIM, Magic Formula, QARP, Multi-factor) + feature_provider tier-aware (A native PiT / B snapshot collected / C bootstrap, con CI assertion para tier-B usage en queries) + citation_resolver + audit_trail. Touchpoints: `contexts/research/{service,scheduler}.py` + `synthesis/*` (`synthesizer.py` ensambla brief con LLM + `citation_resolver.py` resuelve `[fact_id]` markers a research_facts + `audit_trail.py` graba prompts/responses + `prompts/{three_pillar,canslim,magic_formula,qarp,multi_factor}.md`) + `methodology/*` (5 frameworks puros) + `feature_provider/*` (`tier_a.py`, `tier_b.py`, `tier_c.py`) + `api/routes/research.py` (full impl, reemplaza stubs de R1) + `api/sse/research.py` + `cli/research.py` (`refresh-brief <symbol>`, `audit <brief_id>`) + `web/src/routes/(app)/research/[symbol]/{+page,audit-trail/[brief_version]/+page}.svelte` + 5 components (`BriefHeader`, `FactTimeline`, `CitationLink`, `AuditTrailViewer`, `MethodologyBadge`) + tests `tests/integration/test_research_brief_refresh.py` + `tests/unit/contexts/research/{test_audit_trail_render,test_methodology_profiles,test_feature_provider_tier,test_citation_resolver}.py`. Durante dev mocks R2/R3/R4 sources via `SourcePort` fakes para no bloquearse.

### T2. `ibkr-adapter-resilient`

Implementación del `BrokerPort` (definido en T1) sobre `ib_async` con resilience completa: HeartbeatMixin (slice 2) + backoff canonical + reconciliación tras desconexión. Touchpoints: `contexts/trading/brokers/{ibkr_adapter,ibkr_brokerage_model}.py` + tests `tests/integration/{test_ibkr_resilience,test_reconciliation}.py`. Adapter mantiene heartbeat cada 30s con TWS/Gateway; backoff `[3, 6, 12, 24, 48]` al perder conexión; reconciliación al reconectar consulta órdenes/fills perdidos durante el outage y emite eventos de catch-up al MessageBus. `ibkr_brokerage_model.py` modela quirks de IBKR (paper vs live ports, order types, market data subscriptions). Tests integration usan `ib-insync-mock` para no requerir TWS real.

### T3. `donchian-strategy-mvp`

Estrategia v0 implementing `StrategyPort` — Donchian channels + ATR sizing. Touchpoints: `contexts/trading/strategies/{base,donchian_atr,sma_cross,manager}.py` + tests `tests/property/test_strategy_no_lookahead.py` + `config/strategies.yaml` template. `base.py` clase abstracta con hook para no-lookahead enforcement (cada bar solo ve datos `t < now`). `donchian_atr.py` v0 MVP: breakout 20-day high + ATR-based stop. `sma_cross.py` strategy adicional simple para sanity-check del manager. `manager.py` orquesta strategies activas per-tenant. Property test crítico: any strategy + any historical window must NOT use future data.

### O2. `orchestration-scheduler-routines`

Bounded context "orchestration" — scheduler APScheduler + 4 routines (premarket, midday, postmarket, weekly_review) + tier-1 alert filter + report PDF. Touchpoints: `contexts/orchestration/*` (`service.py`, `scheduler.py` APScheduler, `alert_filter.py`, `tier1_alerts.py`, `nodes/{premarket,midday,postmarket,weekly_review}.py`, `report_pdf.py`, `prompts/*` LangGraph nodes) + `migrations/versions/0007_orchestration_tables.py` (`routine_runs`, `alert_events`) + `api/sse/alerts.py` + tests `tests/integration/test_orchestration.py`. Cada routine es un LangGraph workflow que orquesta: collect facts → synthesize brief → filter alerts → publish digest. Cron schedules: premarket 06:30 ET, midday 12:30 ET, postmarket 16:30 ET, weekly_review domingos 18:00 ET.

### R6. `hindsight-integration`

Integración Hindsight como capa narrativa complementaria al SQL bitemporal: write-on day 1 (siempre) + recall togglable per-tenant via `tenants.feature_flags.hindsight_recall_enabled` (default OFF, recommended ON tras ≥12 meses de operación). Touchpoints: `contexts/research/sources/{hindsight_recall,hindsight_retain}.py` + `migrations/versions/0008_tenants_feature_flags.py` (no-op verify si la column ya existe del slice 3) + `api/routes/settings.py` (GET/PUT feature_flags) + `cli/settings.py` (`feature-flag get/set`) + `web/src/routes/(app)/settings/{+page.svelte,+page.server.ts}` (toggle UI) + tests `tests/integration/{test_hindsight_recall_gated,test_hindsight_retain_always_on}.py`. SQL bitemporal sigue siendo source-of-truth para citation chain (NFR-O8) + provenance + audit reproducibility — Hindsight NO reemplaza, complementa con narrativa semántica.

### T4. `trading-routes-and-daemon`

Consolidación final del trading bounded context: rutas API + SSE + CLI + frontend pages full impl + integración E2E. Touchpoints: `api/routes/{trades,portfolio,strategies}.py` (full impl reemplazando stubs de T1) + `api/sse/equity.py` + `cli/{paper,live,propose,export,strategies}.py` (incluye `--confirm-live --i-understand-the-risks` flag per AGENTS.md §7 Override 1) + `web/src/routes/(app)/{trades,portfolio,strategies}/*` + tests `tests/integration/test_proposal_to_fill_flow.py` (E2E happy path) + `tests/integration/test_kill_switch_flow.py` (E2E halt + resume) + `tests/integration/test_cross_tenant_isolation.py` (CRITICAL — NFR-SC1/SC2 verification end-to-end). Esta slice cierra el ciclo: una propuesta cruza propose → risk → approval → execution → fill → equity update → dashboard render.

## Dependency graph (visual)

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
   - `/opsx:propose <slice-id>` → reads this file (`docs/openspec-slice.md`) + generates `openspec/changes/<slice-id>/{proposal.md, specs/<capability>/spec.md, design.md, tasks.md}`
   - Per-artefact worker → QA → verdict (max 2 rework per finding); iter 3 same finding ⇒ `❓ blocked-by-spec`
   - `/opsx:apply <slice-id>` → implementation + tests in branch
   - `/opsx:archive <slice-id>` → promotes specs to `openspec/specs/`, retro at `retros/<slice-id>.md`
4. **CI gates** in branch: lint + type-check + test + secrets scan + license-boundary-check + lighthouse-perf
5. **PR to main**: human reviewer (Gate F equivalent) approves via GitHub + records in `docs/hitl-gates-log.md`
6. **Squash-merge**: branch deleted post-merge; worktree torn down

## Per-slice acceptance criteria template

Each slice's `tasks.md` (generated by `/opsx:propose`) MUST include:

- [ ] All write_paths listed in this slice's scope note are touched and ONLY those (no scope creep)
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
- [.ai-playbook/specs/bmad-openspec-bridge.md](../.ai-playbook/specs/bmad-openspec-bridge.md) §3.1 — canonical schema this file follows
- [.ai-playbook/specs/runbook-bmad-openspec.md](../.ai-playbook/specs/runbook-bmad-openspec.md) §3 — OpenSpec lifecycle each slice follows
