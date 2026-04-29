---
stepsCompleted:
  - step-01-init
  - step-02-context
  - step-03-starter
  - step-04-decisions
  - step-05-patterns
  - step-06-structure
  - step-07-validation
  - step-08-complete
lastStep: 8
status: complete
completedAt: 2026-04-28
inputDocuments:
  - C:/Projects/iguanatrader/docs/prd.md
  - C:/Projects/iguanatrader/docs/backlog.md
  - C:/Projects/iguanatrader/docs/prd-validation-report.md
  - C:/Projects/iguanatrader/AGENTS.md
  - C:/Projects/iguanatrader/docs/runbook.md
  - C:/Projects/iguanatrader/docs/research/oss-algo-trading-landscape.md
  - C:/Projects/iguanatrader/docs/research/feature-matrix.md
  - C:/Projects/iguanatrader/docs/research/platforms/lumibot.md
  - C:/Projects/iguanatrader/docs/research/platforms/nautilustrader.md
  - C:/Projects/iguanatrader/docs/research/platforms/lean.md
  - C:/Projects/iguanatrader/docs/research/platforms/freqtrade.md
  - C:/Users/Arturo/.claude/plans/te-doy-ideas-a-lively-snowglobe.md
workflowType: architecture
project_name: iguanatrader
user_name: Arturo
date: 2026-04-27
updated: 2026-04-28
amendments:
  - 2026-04-28-gate-a-amendment-research-domain-and-backtest-skip
---

# Architecture Decision Document — iguanatrader

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

## Project Context Analysis

### Requirements Overview

**Functional Requirements:** **56 FRs en 8 capability areas** (PRD sealed, capability contract). Implicaciones arquitectónicas más críticas:

| FR cluster | Implicación arquitectónica |
|---|---|
| FR11-FR18 (Trade Lifecycle) | Orden estricto: Strategy → RiskEngine → ApprovalChannel → BrokerInterface. Cualquier shortcut viola FR45. **Pipeline arquitectónico no-bypaseable**. |
| FR19-FR30 (Risk Management) | Risk engine es interceptor obligatorio en hot path. Yaml-declarative + property-tested. **Inyectable como middleware del MessageBus**. |
| FR31-FR38 (Notifications & HITL) | Multi-channel concurrente (Telegram + WhatsApp Hermes). Requiere abstracción `ApprovalChannel` con N implementaciones, fan-out paralelo, reconciliación de respuestas (qué canal respondió primero gana). |
| FR33-FR35 (Tier-graded alerts) | 3 niveles con SLAs distintos: Tier 1 event-driven hardcoded (<60s), Tier 2 polling LLM-filtered (15min), Tier 3 cron schedule fijo. **Diseño con tres trigger sources distintos integrados al MessageBus**. |
| FR39-FR45 (LLM Orchestration & Cost) | LLM nunca en hot path de ejecución. CostMeter wrapper interceptando 100% calls (NFR-O1). Multi-model routing (FR39) → factory pattern + budget cap escalation. |
| FR46-FR51 (Data, Persistence & Audit) | Append-only SQLite con `tenant_id` first-class (NFR-SC1). Estado computable como vista (no DELETE/UPDATE). **Event sourcing pattern light**. |
| FR52-FR56 (Operational Surface) | CLI typer + daemon mode con signal handling. **Dual deployment mode**: one-shot scripting + long-running daemon. |
| FR1-FR5 (Strategy Management) | Per-symbol strategy config yaml-driven, hot-reloadable. **StrategyManager carga + revalida sin reiniciar**. |

**Non-Functional Requirements:** **51 NFRs en 7 quality categories**. NFRs que **fuerzan decisiones arquitectónicas concretas**:

| NFR | Decisión arquitectónica forzada |
|---|---|
| NFR-R1 (30 días IBKR live, 0 uncaught exceptions) | Async event loop con error boundaries por componente; supervisión + restart automático + crash recovery desde event log append-only |
| NFR-R2 (reconciliation broker↔cache 100% post-reconnect) | Cache es fuente de verdad TEMPORAL pero broker es fuente AUTORITATIVA en reconnect. **Reconciliation algorithm con merge semantics explícito** |
| NFR-R5 (kill-switch latency <2s) | Kill-switch como **flag global polled en cada hot path operation**, no como handler async (que podría retrasar). Mecanismos múltiples (file/env/cmd/dashboard) → todos escriben al mismo flag in-memory + persistido. |
| NFR-R6 (property-tested risk caps) | RiskEngine debe ser **función pura testeable con hypothesis** — input: (proposed_order, current_state, config) → output: (allow / reject / clip). Sin side effects internos. |
| NFR-O1 (100% LLM calls logged) | **Decorator/wrapper obligatorio** sobre cliente Anthropic + Perplexity. NO permitir que código de la app llame APIs directamente. |
| NFR-P1 (90% proposals <5s en messaging) | Cliente Telegram/WhatsApp **async non-blocking**. Queue interna con backpressure si el broker de mensajería tarda. |
| NFR-P5 (95% órdenes <3s post-approval) | Path approval → submit es **direct sync await**, no event-bus intermedio (latency budget tight). |
| NFR-SC1 (`tenant_id` first-class) | **Toda query parametrizada con `tenant_id`**; abstraction en repositorio que rechaza queries sin tenant filter. ContextVar para propagación implícita. |
| NFR-SC2 (SQLite → Postgres path) | **Repository pattern + SQLAlchemy** (NO raw SQL hardcoded). Same schema both DBs (sqlmodel + ddl portable). |
| NFR-I1 (BrokerInterface, nuevo adapter <40h) | **ABC + contract test suite reusable**. Adapter de IBKR es la implementación de referencia + benchmark de complejidad. |
| NFR-I3 (prompt caching habilitado, 40-60% hits target) | Anthropic SDK con `cache_control` blocks en system prompts grandes. **Prompt structure designed for cacheability** (estables al inicio, variable al final). |

### Scale & Complexity

**Project complexity: HIGH** (financial risk + technical, NOT regulatory burden).

**Scale indicators:**

- Concurrent users: 1 en MVP (Arturo), ~10-100 en v2 SaaS, ~1000+ en v3
- Concurrent strategies: ~5-10 active symbols × 1-2 strategies each = ~10-20 instancias en MVP
- Trade frequency: 5-20/semana en MVP (DonchianATR + SMA en watchlist pequeña)
- LLM call frequency: ~50-200/día (routines tier-3 + alerts tier-2 + research manual). Budget cap <50€/mes
- IBKR market data: streaming de ~5-50 tickers en MVP, watchlist secundaria opcional hasta SP500+R2000 (Tier 2 alerts)
- Storage growth: SQLite ~10-100 MB en MVP/año

**Architectural components estimated:**

- Core engines: 5 (DataEngine + ExecutionEngine + RiskEngine + Cache + MessageBus) + Kernel orquestador = 6 components
- Brokers/adapters: 1 IBKR en MVP, abstract base + 3-4 adicionales en v2
- Strategies: 2 en MVP, 4-6 en v1.5, 9-12 en v2
- Approval channels: 2 en MVP (Telegram + WhatsApp via Hermes)
- LangGraph nodes: 4 routines + alert filter Tier 2
- Web dashboard pages: 7
- CLI commands: ~16 (typer subcommand groups)
- Config files: 5 yaml + secrets cifrados

**Primary technical domain: Hybrid** — `cli_tool` (primary surface) + `web_app` (dashboard local) + event-driven trading system + LLM orchestration pipeline + automation/scheduling.

### Technical Constraints & Dependencies

**Hardware/OS constraints:**

- Target: Windows 11 Pro (Arturo). Linux compatibility deseable para Docker future + v2 multi-tenant.
- Python 3.11+ obligatorio (asyncio modern features + structural pattern matching + better generics).

**Runtime dependencies (all decided):**

- `ib_async` + TWS Gateway local (broker)
- `anthropic` Python SDK (LLM con prompt caching)
- `perplexity` (news/sentiment)
- `python-telegram-bot` (Telegram approval channel)
- Hermes/Meta Business API (WhatsApp approval channel — reuse, no construir)
- `langgraph` (Capa 3 orchestration)
- `fastapi` + `htmx` + `jinja2` + `plotly` (dashboard)
- `typer` + `rich` (CLI)
- `structlog` (JSON logs)
- `pydantic` + `pydantic-settings` (config + validation)
- `sqlmodel` + `sqlalchemy` (ORM)
- `apscheduler` (cron scheduling — NO crontab del OS por portability)
- `vectorbt` (research-only, Apache + Commons Clause)
- `pytest` + `hypothesis` (testing + property tests)
- `mypy --strict` + `ruff` + `black` (type/lint)
- SOPS + age (secrets encryption)
- `gitleaks` (pre-commit + CI)

**External service dependencies:**

- Anthropic API (Opus 4.7 / Sonnet 4.6 / Haiku 4.5)
- Perplexity API
- Telegram Bot API (free)
- Meta WhatsApp Business API (vía Hermes, número verificado disponible)
- IBKR TWS Gateway + cuenta paper/live

**Constraints temporales y operacionales:**

- Time budget MVP: 3-4 meses calendar
- Bus factor 1 (Arturo): código simple > código clever. **Architecture debe ser comprensible por nuevo dev en <2 días**
- Capital LLM ≤50€/mes: routing decisions deben respetar budget; auto-downgrade Opus→Sonnet→Haiku al exceder

**Constraints hard de AGENTS.md §4:** API keys nunca en commits, sandbox/paper antes que live obligatorio, capital máximo en config, kill-switch obligatorio, logs ejecución inmutables.

### Cross-Cutting Concerns Identified

Concerns que afectan múltiples componentes y que requieren decisión arquitectónica unificada:

1. **`tenant_id` propagation** — desde request entry-point (CLI/Telegram/WhatsApp/Dashboard) hasta SQLite query. Vía `contextvars` + middleware en cada surface.
2. **`structlog` context binding** — `tenant_id`, `proposal_id`, `strategy`, `symbol`, `request_id` propagados automáticamente. Mismo concern que tenant_id pero para observability.
3. **Secrets management** — SOPS+age para at-rest, env vars para runtime. Hot-reload via SIGHUP. Rotación sin downtime (NFR-S8).
4. **Auth/Authorization** — whitelist `authorized_phones` + `authorized_telegram_ids`. Centralizada en config, validada en cada surface entry-point. Bypass attempts loggeados.
5. **Cost metering wrapper** — interceptor obligatorio sobre Anthropic + Perplexity. Architecture debe **forzar el wrapper** (cliente custom inyectado, no SDK direct import).
6. **Time handling** — asyncio event loop time + IBKR timezone (US/Eastern equity) + Madrid (Arturo local) + UTC (logs). Convención explícita requerida.
7. **Reconciliation strategy** — broker↔cache post-disconnect. Algorithm + merge semantics + conflict resolution rules.
8. **Kill-switch as global state** — file + env + cmd + dashboard, todos triggers del mismo flag. Polled en hot path. Idempotent.
9. **Append-only invariants** — NO `UPDATE` ni `DELETE` sobre tablas críticas. Estado mutable computable como view derivada.
10. **Multi-channel approval semantics** — proposal entregada a TODOS los authorized channels en paralelo. Primera respuesta gana, las demás son stale.
11. **LLM cache TTL-based** — `replay_cache.py` simplificado a cache con TTL configurable per node (research/routine/alert), sin bifurcación mode-aware. Backtest fuera de scope MVP (Gate A amendment 2026-04-28). Cache key incluye `prompt_hash` + `model` + `node` + `tenant_id`.
12. **Property test invariants globales** — RiskEngine.evaluate() función pura. Pydantic models inmutables. Append-only enforcement via type system donde posible.

### Architectural North Star

Defensive design **encoded in types y contracts** (pydantic immutable models, ABC con default impls, contextvars con required-fields), no en runtime checks. **El sistema debe ser difícil de usar mal desde dev-time** — bus factor 1 + 3-4 meses de budget no permiten que el dev del lunes se pelee con boilerplate o se olvide de invariants. La arquitectura es la red de seguridad.

## Starter Template Evaluation

### Primary Technology Domain

**Hybrid system** sin fit limpio en starter category single:

- **Surface principal interactiva**: SPA con Svelte 5 + SvelteKit (web app) sirviendo dashboard + onboarding + admin
- **Surface CLI**: typer-based para scripting + daemon mode (paper / live / dashboard server)
- **Backend pattern**: API-first event-driven trading con orchestration LLM-augmented + cron schedules + multi-channel approval gate
- **Persistence**: SQLite local append-only con multi-tenant ready schema; path migration a Postgres cuando corresponda
- **Distinctive concerns**: streaming reactivity multi-instrument (10-20 stocks live), cost observability del LLM stack, risk engine declarativo no-bypaseable, **bitemporal knowledge repository per-symbol con provenance + show-your-work** (Research & Intelligence domain, FR57-FR79)

Ningún starter público cubre la composición. Adoptamos hybrid skeleton: tooling base + AI-assisted scaffolding.

### Selected Approach: Hybrid Skeleton (backend) + Svelte 5 SPA (frontend)

#### Backend skeleton

Cookiecutter Python skeleton (Poetry-based, BSD/MIT verificable al implementar) como base de tooling Python. Resuelve scaffolding ortogonal: pyproject.toml con tool configs (mypy strict, ruff, black, pytest, coverage), pre-commit hooks, GitHub Actions CI matrix, gitignore, Makefile/taskfile. AI-assisted scaffolding (Claude Code) genera el resto basándose en los 56 FRs y 51 NFRs ya documentados: Dockerfile multi-stage + docker-compose, structlog setup con contextvars binding, pydantic-settings layering 5-niveles, SQLAlchemy + sqlmodel scaffold con `tenant_id` enforcement repository pattern, fixtures pytest comunes.

#### Frontend skeleton

**SvelteKit project** (`pnpm create svelte@latest iguanatrader-web`) con TypeScript strict, Vite build, Tailwind CSS 4.x, `@sveltejs/adapter-node` para deployment standalone (compatible con Docker single-image o separate container).

#### Backend architecture: API-first

```
┌───────────────────────────────────────────────────────────┐
│  Service Layer (lógica negocio, frontend-agnostic)         │
│  StrategyService, RiskService, ApprovalService,            │
│  CostService, BrokerService, ResearchService,              │
│  PortfolioService, TenantService                           │
└──────────┬──────────────────────────────┬────────────────┘
           │                              │
           ▼                              ▼
   ┌────────────────┐            ┌─────────────────────┐
   │ JSON API layer │            │ SSE endpoints layer │
   │ FastAPI routes │            │ FastAPI routes      │
   │ retorna JSON   │            │ EventSourceResponse │
   │ DTOs Pydantic  │            │ push events         │
   └────────┬───────┘            └────────┬────────────┘
            │                              │
            └──────────┬───────────────────┘
                       │
                Consumido por:
            ┌──────────┴───────────┐
            │                      │
   ┌─────────────────┐   ┌──────────────────┐
   │ Svelte 5 SPA    │   │ CLI (typer)      │
   │ frontend        │   │ scripting + ops  │
   │ (browser)       │   │                  │
   └─────────────────┘   └──────────────────┘
```

Tipos compartidos backend↔frontend vía OpenAPI schema autogenerado por FastAPI → TypeScript types via `openapi-typescript` o similar. **Single source of truth** para DTOs.

### Architectural Decisions Provided by Hybrid Skeleton

| Layer | Decisión |
|---|---|
| Language backend | Python 3.11+ |
| Language frontend | TypeScript strict |
| Package manager backend | Poetry (lockfile + reproducibility) |
| Package manager frontend | pnpm (preferido sobre npm/yarn por velocidad + estricto) |
| Project layout backend | `src/iguanatrader/` layout |
| Project layout frontend | SvelteKit conventions (`src/routes/`, `src/lib/`, `src/lib/components/`, `src/lib/stores/`) |
| Test framework backend | pytest + hypothesis (property tests) |
| Test framework frontend | Vitest (unit) + Playwright (e2e) |
| Type checking | mypy --strict (backend), tsc strict + svelte-check (frontend) |
| Linting/formatting | ruff + black (backend), eslint + prettier (frontend) |
| Pre-commit | gitleaks + ruff + black + mypy + check-toml + eslint + prettier |
| CI | GitHub Actions matrix Python 3.11/3.12 + Node 20/22; lint + type-check + test + secrets scan |
| Containerization | Docker multi-stage (Python backend + Node frontend build → Nginx serve assets, FastAPI sirve API/SSE) |
| Logging | structlog JSON con contextvars binding (`tenant_id`, `proposal_id`, `strategy`, `symbol`, `request_id`) |
| Config | pydantic-settings layering: CLI > ENV > SOPS-encrypted > yaml > defaults |
| Persistence ORM | SQLAlchemy + sqlmodel; repository pattern con `tenant_id` enforcement |
| Migration tool | Alembic (para v1.5+ cuando schema evolucione + path SQLite → Postgres v2) |
| Frontend reactivity | Svelte 5 runes (`$state`, `$derived`, `$effect`, `$props`) |
| Frontend state mgmt | Svelte stores para shared state (per-tenant); runes para component-local |
| Frontend routing | SvelteKit file-based routing (`src/routes/`) |
| Frontend forms | SvelteKit form actions con progressive enhancement |
| Frontend SSR / streaming | SvelteKit SSR + streaming via `await` blocks (Svelte 5) |
| Frontend animations | Built-in (`transition:`, `animate:flip` para stock reordering) |
| Frontend HTTP client | `fetch` nativo + `+page.ts/+page.server.ts` load functions |
| Frontend SSE consumption | `EventSource` API directo en composables Svelte |
| Charts streaming | TradingView Lightweight Charts (free tier, optimized para tick streaming) |
| Charts research dashboards | ApexCharts o Plotly.js (multi-axis fundamentals visualization, equity curve historical, cost breakdown) |
| CSS | Tailwind CSS 4.x + Svelte scoped styles |
| Mobile-responsive | Tailwind mobile-first + Svelte responsive utilities; PWA-ready vía SvelteKit adapter cuando corresponda |
| Authentication | Cookie-based sessions (HttpOnly secure) — diferimos detalle a Step 4 |
| Tipos backend↔frontend | OpenAPI schema autogenerado FastAPI → openapi-typescript → tipos TS consumidos por Svelte |

### Lo que el skeleton NO decide y se establece en pasos siguientes

- Estructura interna de módulos (Core engines, capa de approval, etc.) — **Step 6 Structure**
- Patterns arquitectónicos del dominio (MessageBus, Repository, RiskEngine flow) — **Step 5 Patterns**
- Decisiones específicas adicionales (auth flow detalle, SSE protocol semantics, charting library final, monorepo vs multi-repo) — **Step 4 Decisions**
- Topology de deployment + estrategia multi-tenant v2 — **Step 4 Decisions**
- Estrategia de testing en detalle (qué tests son CI-blocking, coverage targets por módulo, e2e scenarios) — **Step 4 Decisions**

### Versiones objetivo (verificables al implementar M1)

- `python` 3.11.x o 3.12.x
- `poetry` ≥ 1.8 (lockfile v2 estable)
- `node` 20 LTS o 22 LTS
- `pnpm` ≥ 9
- `svelte` 5.x (con runes)
- `sveltekit` 2.x
- `vite` 5.x
- `typescript` 5.x strict
- `tailwindcss` 4.x
- Verificación de versiones obligatoria al primer `poetry install` + `pnpm install` en M1

### Frontend stack rationale (post Party Mode + user pushback)

La elección Svelte 5 + SvelteKit sobre alternativas es deliberada por los siguientes criterios técnicos:

- **Streaming reactivity multi-instrument**: 10-20 stocks ticking 5-50/seg cada uno requiere fine-grained reactivity. Svelte 5 runes + compiler optimization producen código equivalente a vanilla JS optimizado.
- **Bundle size mobile cold-start**: runtime ~3-4KB gzipped vs alternativas más pesadas. Critical para v3 SaaS users en móvil.
- **List reordering animations**: directiva `animate:flip` built-in para stocks reordenándose por momentum live. Sin lib externa.
- **End-to-end type safety**: `+page.server.ts` load returns auto-inferidos en `+page.svelte`, reduce bugs en boundaries.
- **Form actions con progressive enhancement**: superior a alternativas para form-heavy onboarding/config v3 SaaS.
- **Maturity SvelteKit 2.x**: battle-tested en producción; conventions probadas para multi-tenant SaaS.
- **Trade-off explícito aceptado**: governance backed por Vercel introduce riesgo de pattern-lock-in (similar trayectoria a Next.js); mitigación = mantener API-first backend desacoplado, frontend reemplazable si en v3 surge razón.

Decisión HTMX original del PRD reemplazada por SPA tras pushback de architect roundtable + user analysis del use case streaming multi-stock con actions. La complejidad adicional del SPA stack es proporcional al valor preservado para v3 trajectory.

### Initialization Plan (M1 Foundation work, NO architecture work)

```bash
# Backend
poetry new --src iguanatrader-api  # o cookiecutter-poetry equivalente
cd iguanatrader-api
poetry add fastapi uvicorn anthropic perplexity ib-async typer rich structlog \
  pydantic pydantic-settings sqlmodel sqlalchemy alembic apscheduler \
  python-telegram-bot langgraph vectorbt
poetry add --group dev pytest pytest-asyncio hypothesis mypy ruff black

# Frontend
pnpm create svelte@latest iguanatrader-web
cd iguanatrader-web
pnpm add -D @sveltejs/adapter-node vitest @playwright/test
pnpm add openapi-typescript

# Decisión monorepo vs multi-repo + tooling cross-package: Step 4

# AI-assisted scaffolding: Claude Code genera Dockerfile, structlog config, pydantic-settings
# layering, fixtures, SvelteKit auth hooks, OpenAPI client setup, basándose en FRs/NFRs.
# Revisión humana ~3-4h antes de empezar lógica de dominio.
```

### Note arquitectónico

Este Step 3 establece **el qué** del skeleton. **El cómo** se ejecuta como primera implementation story M1 Foundation del backlog. Architecture documenta decisiones; bootstrap del código es work del implementer.

## Core Architectural Decisions

### Decision Priority Analysis

**Decisiones cerradas en steps 2-3** (no re-litigar): stack backend/frontend, persistence engine, API style, logging primitives, secrets, container, CI, license, risk engine principles, approval channels, LLM routing.

**Critical decisions (block implementation)**: data retention policy, repo strategy, monitoring stack integration.

**Important decisions (shape architecture)**: caching strategy, backup strategy, query patterns, web auth, password hashing, CSRF protection, rate limiting, multi-tenant context propagation, API versioning, error format, SSE protocol semantics, repo strategy.

**Deferred decisions (post-MVP)**: 2FA/MFA → v3, i18n → v3 SaaS, accessibility WCAG full → v3, hosting target v2/v3 (re-evaluable), CD automation → v1.5+.

### Data Architecture

| Decisión | Resolución |
|---|---|
| Database engine | SQLite append-only WAL mode MVP → Postgres v2 path (ADR-002 PRD) |
| ORM | SQLAlchemy + sqlmodel; repository pattern con `tenant_id` enforcement obligatorio (NFR-SC1) |
| Migrations | Alembic |
| Time-series cache (bars históricos) | Parquet files via pandas/duckdb readers |
| **Caching strategy hot path** | `cachetools` LRU/TTL in-process para reads frecuentes (config, watchlist, current positions cache). Sin Redis en MVP. Redis re-evaluable en v2 si benchmark muestra contención |
| **Backup strategy SQLite** | `litestream` continuous replication desde MVP (folder local primero, S3-compatible cuando v2 cloud). Restore documentado en runbook. Backup test mensual obligatorio |
| **Query patterns** | sqlmodel para 95% queries (type-safe + Pydantic-aligned). SQL raw vía `text()` SQLAlchemy SOLO para reportes complejos en `/runs` o aggregates con CTEs. NO ORM propio |
| **Read/write split** | SQLite WAL mode habilitado (concurrent reads + serial writes). Suficiente MVP single-user. v2 multi-tenant per-container = no contención cross-tenant |
| **Data retention policy** | **Forever en MVP. Cuando sea problema, crearemos policy de archive (decisión 2026-04-28).** No implementar archive infrastructure preemptive |

### Authentication & Security

| Decisión | Resolución |
|---|---|
| Secrets at-rest | SOPS+age (NFR-S1) |
| Secrets in CI | gitleaks pre-commit + CI block (NFR-S2); tokens en GitHub Secrets |
| Authorized senders messaging | `authorized_phones` + `authorized_telegram_ids` whitelist (NFR-S3, NFR-S4) |
| **Web dashboard auth (MVP)** | Cookie-based session vía FastAPI custom middleware. Login con username + password (1 user en MVP = Arturo). Session token = signed JWT en cookie HttpOnly+Secure+SameSite=Strict. Lifetime 7 días con sliding window |
| **Password hashing** | `argon2-cffi` (Argon2id) — current best practice 2026 |
| **Auth library** | Bespoke custom para MVP single-user (trivial). v2 multi-user evalúa `fastapi-users` o seguir bespoke según traction |
| **CSRF protection** | `SameSite=Strict` cookies + Origin header check en endpoints state-changing. SvelteKit `csrf.checkOrigin` built-in cubre frontend |
| **2FA/MFA** | NO en MVP. Plan v3: TOTP (`pyotp`) cuando haya users múltiples post-SaaS launch |
| **Rate limiting** | `slowapi` middleware FastAPI. Per-IP en login (5/min), per-tenant en API endpoints (60/min default, configurable). MVP relaxed; v3 SaaS stricter |
| **Session storage** | JWT stateless en cookie (no server-side session store). Trade-off acknowledged: revocación requiere short lifetime + refresh token o blacklist; MVP single-user 7 días sin blacklist es aceptable |
| **Multi-tenant context propagation** | `tenant_id` extraído de JWT claim → `contextvars.ContextVar` → propagado automáticamente a todas queries vía SQLAlchemy event listener que **rechaza queries sin filter `tenant_id`**. Defensive design: query sin tenant filter throws en dev, logs warning + denies en prod. Mismo `contextvars` propaga a structlog |

### API & Communication Patterns

| Decisión | Resolución |
|---|---|
| API style | REST/JSON via FastAPI + SSE para streams |
| OpenAPI docs | FastAPI built-in `/api/docs` (Swagger UI) y `/api/redoc` |
| Tipos cross-stack | OpenAPI schema autogenerado → `openapi-typescript` → tipos TS compartidos. Pre-commit hook regenera + valida diff |
| **API versioning** | URL path `/api/v1/...` desde día 1. Cuando v2 SaaS introduzca breaking changes, `/api/v2/...` coexiste con v1 durante deprecation window documented |
| **Error response format** | RFC 7807 `application/problem+json`: `{type, title, status, detail, instance, ...extensions}`. FastAPI custom exception handler convierte HTTPException + custom domain errors. Frontend consume tipos error vía openapi-typescript |
| **SSE event protocol** | Typed events con `event:` field + `id:` para resume + `data:` JSON payload + `retry: 5000` para auto-reconnect. Tipos eventos definidos como Pydantic models (ej. `FillEvent`, `RiskCapEvent`, `ApprovalEvent`, `CostEvent`). Tipos TS auto-generados igual que JSON DTOs |
| **API client frontend** | Native `fetch` + types from `openapi-typescript` + thin wrapper en `src/lib/api/client.ts`. NO TanStack Query / SWR en MVP (overhead innecesario single-user). v3 SaaS reevalúa si caching/dedup needs emergen |
| **Webhooks inbound** | WhatsApp Meta webhooks vía Hermes (reuse). IBKR usa TWS Gateway local con socket persistent (`ib_async`) — NO webhooks. Sin webhooks adicionales en MVP |

### Frontend Architecture (deltas sobre Step 3)

| Decisión | Resolución |
|---|---|
| Loading states | Svelte 5 `await` blocks en templates + spinners Tailwind. Cancel button en operaciones largas (research_brief refresh, bulk EDGAR download) |
| Error boundaries | `+error.svelte` files de SvelteKit per route. Global error handler en `src/hooks.client.ts` reporta a Eligia OTel collector (ver §Infrastructure) |
| PWA enablement | `vite-plugin-pwa` configurado pero **disabled en MVP**. Activar en v2 cuando dashboard se exponga fuera de localhost |
| i18n | NO en MVP (single-user). v3 SaaS evalúa `svelte-i18n` o `paraglide` |
| Accessibility | WCAG 2.1 AA target en v3 SaaS. NO en MVP. `eslint-plugin-svelte` con a11y rules habilitado desde día 1 (catch low-hanging) |
| Theme (light/dark) | Tailwind dark mode + system preference desde MVP |

### Infrastructure & Deployment

| Decisión | Resolución |
|---|---|
| Container | Docker multi-stage |
| Compose orchestration MVP | docker-compose con perfiles dev / paper / live |
| **Repo strategy** | **Monorepo single GitHub repo (decisión 2026-04-28).** Estructura: `apps/api` (Python backend) + `apps/web` (SvelteKit frontend) + `packages/shared-types` (auto-generated TS from OpenAPI). Tooling: pnpm workspace + Poetry workspace. Razón: cross-cutting changes (DTO update → TS regen → frontend uses new type) atómicos en single PR; bus factor 1 prefiere fricción minimizada |
| **Hosting MVP** | Localhost en Arturo's Windows 11 Pro. Docker Compose levanta backend + frontend + opcional TWS Gateway sidecar |
| **Hosting v2 (multi-tenant beta)** | Hetzner / OVH VPS dedicado o cloud (DigitalOcean / Fly.io) con Docker Compose multi-tenant pattern (1 container API + 1 container web + Postgres managed + per-tenant API instance escalable). NO Kubernetes en v2 — overkill |
| **Hosting v3 SaaS** | Re-evaluar en v3. Probables: Fly.io, Railway, AWS ECS/Fargate, GKE. Decisión gated por scale real |
| **Environment configuration** | 3 perfiles: `dev` (local Arturo), `paper` (IBKR paper account), `live` (IBKR real money). Yaml files separados + ENV overrides. Switch via `IGUANA_ENV=paper` env var |
| **Monitoring & metrics** | **Eligia-citizen pattern (decisión 2026-04-28).** iguanatrader emite **OpenTelemetry traces + structlog JSON logs Eligia-compatible** vía OTLP exporter. Eligia ya provee LangGraph + OpenTelemetry collector + dashboard service-status. iguanatrader **no construye obs stack propio** — reusa el de Eligia. Cuando el dashboard Eligia esté terminado, se hará integration spec específico (Arturo flagged: "te pedire leerlo para ver que metricas sacaremos desde ahi"). Implicación: structlog processor adicional emite OTLP; spans definidos en hot paths críticos (RiskEngine.evaluate, BrokerInterface.submit, LLM call, ApprovalChannel.deliver). Sentry-equivalent NO necesario — Eligia lo cubre |
| **Backup strategy** | `litestream` continuous replication desde MVP. Restore docs en runbook. Backup test mensual |
| **CD / deployment automation** | **NO auto-deploy a live** desde día 1 (constraint AGENTS.md §4). Manual `docker compose up` para paper/live. CI build images en GHCR; deploy manual via SSH + compose pull. v3 SaaS evalúa GitOps cuando aplique |
| **TWS Gateway management** | Proceso separado del Docker stack. Arturo lanza manualmente TWS Gateway en su Windows host; container API conecta vía host network o port forwarding. Documentar restart procedure en runbook (heartbeat NFR-P8 detecta crashes; restart manual hasta automatizar en v1.5+) |
| **Disaster recovery** | Docs runbook explícito: scenarios (TWS down, broker disconnect, SQLite corrupt, kill-switch stuck, LLM API outage, OTLP collector down). Cada uno con detection signal + recovery steps + RTO/RPO targets. Append-only schema = RPO ~1h con litestream, RTO ~minutos |
| **Eligia alerting rules (heartbeats)** | iguanatrader emite OTel gauges `iguana_<adapter>_heartbeat_last_ts` (UNIX timestamp UTC). Eligia define alerting rules en su propio repo: `time() - iguana_ibkr_heartbeat_last_ts > 90` → Telegram alert (NFR-P8). Mismo patrón para `telegram`, `hermes`, `daemon`. **iguanatrader emite metrics; Eligia raises alerts**. Defense-in-depth: Capa 1 detecta in-process via MessageBus; Capa 2 (Eligia) detecta daemon-completely-dead silence |
| **WhatsApp templates pre-approval (NFR-I6)** | Concern operacional, no architectural. Add a `docs/runbook.md` section "v1.0 release checklist" con bullet: "Submit WhatsApp message templates for `proposal_received`, `risk_breached`, `kill_switch_activated`, `weekly_review_ready` to Meta Business approval queue ≥7 días antes de v1.0 launch. Verify approval status via Meta Business Manager. Token rotation procedure (NFR-S8) verifies hot-reload without downtime." |

### Liveness & Resilience Specifications

Specs concretos por NFR (canónicos para implementation):

| NFR | Spec |
|---|---|
| **NFR-P8** IBKR heartbeat | `IBKRAdapter._heartbeat_loop()` async task, sleep `30s` entre ticks. Cada tick: `ib.isConnected()` check + emit OTel gauge + emit MessageBus `trading.broker.heartbeat` event. Gap > `90s` (Eligia rule) → Telegram alert. Implementado vía `shared/heartbeat.py:HeartbeatMixin` |
| **NFR-R7 / NFR-I2** IBKR reconnect backoff | `BACKOFF_SCHEDULE_S = [3, 6, 12, 24, 48]` (5 attempts). Tras 5 consecutive fails → emit `risk.kill_switch.activated` event con reason `broker_unreachable`. Implementado en `IBKRAdapter._reconnect_with_backoff()` reusando primitive `shared/backoff.py:exponential_backoff()` |
| **NFR-I4** Perplexity rate limit | `PerplexityClient` wrapper en `contexts/observability/perplexity_throttle.py` con token bucket: `max_rpm` configurable (default 20). Excedente → queue async + backoff exponencial. Drop policy si queue > 100 pending: oldest discarded + structlog WARNING |
| **NFR-I5** Telegram polling resilience | `python-telegram-bot` long-polling tiene auto-reconnect built-in (verified vía contract test `tests/integration/test_telegram_resilience.py` simula disconnect 30s). Wrapper en `channels/telegram.py` añade: (1) heartbeat task vía mismo `HeartbeatMixin`, (2) message queue persistido en SQLite si bot disconnected (re-enqueue al reconnect) |
| **NFR-O3** Log rotation | structlog → `logging.handlers.RotatingFileHandler` con `maxBytes=100MB`, `backupCount=7`. Configurado en `observability/structlog_config.py`. Retention overridable vía `config.iguana.yaml:logging.retention_days`. Compresión .gz tras rotación (built-in). Logs path: `logs/iguana.YYYY-MM-DD.log` (date suffix vía `TimedRotatingFileHandler` daily roll) |
| **NFR-O4** Cost dashboard refresh | `/api/v1/sse/costs` endpoint (`api/sse/costs.py`) consume MessageBus `observability.cost.logged` events directly + emite tick consolidado cada **5min** vía dedicated publisher `contexts/observability/cost_dashboard_publisher.py`. Frontend `web/src/lib/composables/useCostStream.ts` consume. Trade-off: real-time push vía bus events + 5min consolidated tick para aggregates costosos (cost-per-trade ratio, daily totals). Ambos formatos en mismo SSE stream con `event:` field discriminator |
| **NFR-P7** Dashboard <500ms localhost | SvelteKit SSR + Tailwind purge + Vite production build. **Lighthouse CI** integrado en `.github/workflows/ci.yml` step `lighthouse-perf`: assertion fail si `largest-contentful-paint > 500ms` en localhost build. Budget config en `apps/web/lighthouserc.json` |
| **NFR-P9** Research_brief refresh <30s | `ResearchService.refresh_brief(symbol)` orchestrates parallel source fetches + LLM synthesis. Target ≥40% prompt cache hit ratio (Anthropic `cache_control` blocks en system prompt estable). Per-symbol timeout 30s; partial brief con citations resueltas se persiste con flag `partial=true` si timeout (fallback graceful) |
| **NFR-O8** Citations resolved 100% | `synthesis/citation_resolver.py` valida que cada `[fact_id]` cita en draft existe en `research_facts` table del tenant; broken citations en CI render → fail; en live render → soft-fail con WARNING + brief marked `citations_partial=true` |

### OpenBB Sidecar Topology (FR76)

OpenBB Platform corre como **proceso isolated** preservando boundary AGPL-3.0 ↔ Apache-2.0+CC. Decisión cerrada per Gate A amendment 2026-04-28; ADR-015 documenta detalle.

| Aspecto | Resolución |
|---|---|
| **Deployment unit** | Docker container separado: `apps/openbb-sidecar/Dockerfile` con `pyproject.toml` independiente (deps OpenBB AGPL no entran a iguanatrader Apache+CC) |
| **Communication** | HTTP loopback only — `localhost:8765` (FastAPI minimalista expone solo endpoints que iguanatrader consume) |
| **iguanatrader client** | `contexts/research/sources/openbb_sidecar.py` usa `httpx.AsyncClient` exactamente como cualquier otro adapter externo |
| **Resource limits k3s** | `requests: {cpu: 500m, memory: 1Gi}`, `limits: {cpu: 1, memory: 2Gi}` — basado en perfil idle ~400-600 MB + peaks ~1.5 GB en heavy queries |
| **VPS impacto** | Hetzner CAX31 actual (16 GB RAM, 8 vCPU): cómodo, sin upgrade necesario. ~10% extra resource consumption |
| **Liveness** | `HeartbeatMixin` desde `shared/heartbeat.py` aplicado al sidecar adapter; ping a `localhost:8765/health` cada 30s; gap > 90s emite OTel gauge a Eligia → alert |
| **Endpoints exposed** | `/health` (liveness), `/v1/equity/fundamentals/{symbol}`, `/v1/equity/ratings/{symbol}`, `/v1/equity/esg/{symbol}`, `/v1/economy/macro/{indicator}` — minimal subset que iguanatrader necesita; expandible bajo demanda |
| **Versioning** | OpenBB pinned a versión específica en sidecar `pyproject.toml`; iguanatrader nunca depende de breaking changes upstream sin update controlado |
| **Failover** | Si sidecar down: source adapter retorna `None` → research_brief para ese symbol marca `partial=true` con fact list reducida; brief sigue válido sin facts OpenBB |
| **License boundary tests** | Pre-commit hook + CI verifica que `apps/api/pyproject.toml` NO tiene OpenBB en deps (drift_check); cross-import desde `apps/api/` a `apps/openbb-sidecar/` codebase prohibido |

### Decision Impact Analysis

**Cross-component dependencies importantes:**

1. **`tenant_id` propagation** afecta: auth (extracción de JWT) → contextvars → SQLAlchemy event listener → todo query → todo log structlog → todo OTel span attribute. **Una decisión, 6 puntos de implementación**.
2. **OpenAPI tipo TS pipeline** afecta: cualquier cambio de DTO Pydantic → script regen TS → frontend rebuild. Pre-commit hook regenera + valida diff.
3. **SSE event types** son DTOs Pydantic compartidos backend↔frontend igual que API JSON; mismo pipeline.
4. **`tenant_id` en JWT** y en cookie session implica: refresh token cuando tenant cambia (raro), single-tenant per session asumido.
5. **`litestream` + WAL mode SQLite** son orthogonal: litestream replica el WAL stream, no lock files.
6. **Eligia OTel integration** afecta: structlog processor adicional, spans manuales en hot paths críticos, dashboard config externo a iguanatrader (mantenido en Eligia repo).

### Implementation Sequence (orden recomendado en M1)

1. Bootstrap **monorepo** (apps/api + apps/web + packages/shared-types) + skeletons backend/frontend + CI básica
2. SQLite + sqlmodel + Alembic + tenant_id pattern + SQLAlchemy event listener (NO data aún)
3. Auth básica (Argon2id + cookie session + JWT) + tenant context propagation via contextvars
4. FastAPI estructura `/api/v1/` + OpenAPI + tipos TS pipeline + RFC 7807 error format
5. structlog + pydantic-settings + secrets SOPS + **OTel exporter Eligia**
6. Docker compose con perfiles dev/paper/live + litestream backup
7. **(luego entran patterns Step 5: MessageBus, RiskEngine, etc.)**

## Implementation Patterns & Consistency Rules

### Critical Conflict Points Identified

~25 áreas potenciales donde AI agents podrían divergir. Cada una resuelta con regla explícita + ejemplo + anti-patrón. Estructura: **DDD-lite con bounded contexts** (decisión 2026-04-28).

### Naming Patterns

#### Database

| Concern | Regla | Ejemplo good | Anti-pattern |
|---|---|---|---|
| Tables | `snake_case` plural | `trades`, `risk_overrides`, `api_cost_events` | `Trade`, `Risk_Override`, `riskOverrides` |
| Columns | `snake_case` | `tenant_id`, `created_at`, `entry_price` | `tenantId`, `EntryPrice` |
| Primary keys | `id` (uuid v4 stored as string) | `id: UUID` | `trade_id` para PK del table `trades` |
| Foreign keys | `<reference>_id` | `tenant_id`, `proposal_id` | `fk_tenant`, `tenantRef` |
| Indexes | `ix_<table>_<columns>` (SQLAlchemy default) | `ix_trades_tenant_id_created_at` | `idx_trades_by_tenant` |
| Constraints | `ck_<table>_<rule>`, `uq_<table>_<columns>`, `fk_<table>_<column>_<ref>` | SQLAlchemy default naming convention | Custom inconsistent |

#### API endpoints

| Concern | Regla | Ejemplo good |
|---|---|---|
| Path style | `kebab-case` plural for collections | `/api/v1/trades`, `/api/v1/risk-overrides`, `/api/v1/auth/login` |
| Path params | `{snake_case}` | `/api/v1/trades/{trade_id}` |
| Query params | `snake_case` | `?from_date=2026-04-01&max_results=50` |
| HTTP verbs | RFC 7231 standard | GET / POST / PATCH / PUT / DELETE |
| Status codes | 200/201/204/400/401/403/404/409/422/429/500/503 específicos | Específicos por caso |
| Headers custom | Sin `X-` prefix (RFC 6648) | `Iguana-Tenant-Id`, `Iguana-Request-Id` |

#### JSON wire format

| Concern | Regla | Ejemplo good |
|---|---|---|
| Field naming | `camelCase` over the wire vía Pydantic `alias_generator=to_camel` + `populate_by_name=True` | `{"tenantId": "...", "createdAt": "..."}` |
| Backend internal | `snake_case` PEP 8 | `model.tenant_id` |
| Frontend internal | `camelCase` idiomatic TS | `dto.tenantId` |
| Conversion | Automática Pydantic + openapi-typescript | — |

#### Code (backend)

| Concern | Regla | Ejemplo good |
|---|---|---|
| Modules / packages | `snake_case` | `risk_engine.py`, `broker_interface.py` |
| Classes | `PascalCase` | `RiskEngine`, `IBKRAdapter`, `TradeProposal` |
| Functions / methods | `snake_case` | `submit_order()`, `compute_pnl()` |
| Constants | `UPPER_SNAKE_CASE` | `DEFAULT_RISK_PER_TRADE = Decimal("0.02")` |
| Private | `_leading_underscore` | `_internal_helper()` |
| Type aliases | `PascalCase` | `TenantId = NewType("TenantId", UUID)` |

#### Code (frontend)

| Concern | Regla | Ejemplo good |
|---|---|---|
| Components Svelte | `PascalCase.svelte` | `StockRow.svelte`, `EquityCurve.svelte`, `KillSwitchButton.svelte` |
| Module TS | `camelCase.ts` | `apiClient.ts`, `tenantContext.ts`, `dateFormat.ts` |
| Stores | `<concern>Store.ts` con factory function | `tenantStore.ts` exporting `createTenantStore()` |
| Functions | `camelCase` | `fetchTrades()`, `formatPrice()` |
| Constants | `UPPER_SNAKE_CASE` | `DEFAULT_PAGE_SIZE = 50` |
| SvelteKit special | `+page.svelte`, `+layout.svelte`, `+error.svelte`, `+server.ts` (convention SvelteKit, intocable) | — |

### Structure Patterns (DDD-lite con bounded contexts)

#### Monorepo layout

```
iguanatrader/                                      # repo root (monorepo)
├── apps/
│   ├── api/                                       # Python backend
│   │   ├── src/iguanatrader/
│   │   │   ├── contexts/                          # Bounded contexts (DDD-lite)
│   │   │   │   ├── trading/                       # Strategy, Proposal, Trade, BrokerInterface
│   │   │   │   ├── risk/                          # RiskEngine, Protections, Caps
│   │   │   │   ├── approval/                      # Multi-channel approval gate
│   │   │   │   ├── observability/                 # CostMeter, OTel, structlog
│   │   │   │   ├── orchestration/                 # LangGraph routines + cron
│   │   │   │   └── research/                      # Bitemporal knowledge repo + multi-source ingestion + LLM briefs
│   │   │   ├── shared/                            # Cross-context primitives (MessageBus, types base, errors, contextvars)
│   │   │   ├── api/                               # FastAPI delivery layer (routes + DTOs + auth + errors)
│   │   │   ├── persistence/                       # SQLAlchemy session + tenant_listener + Alembic migrations
│   │   │   ├── cli/                               # typer commands
│   │   │   ├── config.py                          # pydantic-settings layering 5-niveles
│   │   │   └── main.py                            # FastAPI app factory + Kernel boot
│   │   ├── tests/{unit,integration,property}/
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   └── web/                                       # SvelteKit frontend
│       └── src/{routes,lib/{api,components,stores,utils,types}}/
├── apps/openbb-sidecar/                           # AGPL-isolated OpenBB Platform Docker container (FR76)
├── packages/shared-types/                         # Auto-generated TS types from OpenAPI
├── config/{iguana,risk,strategies,llm_prices,research,watchlist}.yaml
├── .secrets/                                      # gitignored, SOPS-encrypted
├── docs/                                          # PRD + architecture + research + runbook + ADRs (docs/adr/)
├── docker-compose{,.paper,.live}.yml
├── pnpm-workspace.yaml
├── pyproject.toml                                 # Poetry workspace root
├── Makefile
├── LICENSE                                        # Apache-2.0 + Commons Clause
└── THIRD_PARTY_NOTICES.md                         # attribution si entra código externo
```

#### Estructura interna de cada context (DDD-lite)

```
contexts/<context>/
├── __init__.py            # Public API del context (re-exports). Cross-context calls SOLO via aquí
├── models.py              # Pydantic + sqlmodel domain models del context
├── ports.py               # Interfaces (BrokerInterface, ApprovalChannel, etc.) que el context expone
├── service.py             # Use cases / application service del context
├── repository.py          # Data access layer del context (recibe session inyectada)
└── <subdomain>/           # Sub-folders cuando aplique (ej. trading/strategies/, trading/brokers/)
```

#### Bounded contexts identificados (6 en MVP — backtest removed 2026-04-28, research added)

| Context | Responsabilidad | Aggregate roots |
|---|---|---|
| **trading** | Strategy lifecycle, BrokerInterface, Trade/Order/Fill flow | `Strategy`, `TradeProposal`, `Trade`, `Order` |
| **risk** | RiskEngine evaluación + Protections + Override audit | `RiskEvaluation`, `RiskOverride`, `Protection` |
| **approval** | Multi-channel approval gate, authorized senders, decisions | `ApprovalRequest`, `ApprovalDecision`, `ApprovalChannel` |
| **observability** | Cost metering, OTel exporter, structured logs config | `ApiCostEvent`, `Span`, `LogEvent` |
| **orchestration** | LangGraph routines (premarket/midday/postmarket/weekly) + Tier 1/2/3 alerts + cron | `Routine`, `Alert` |
| **research** | Bitemporal knowledge repo per-symbol; multi-source ingestion (SEC EDGAR, FRED, Finnhub, GDELT, openFDA, OpenInsider, OpenBB sidecar); LLM-synthesized research_briefs con citations + audit_trail; methodology configurable per-watchlist | `WatchlistConfig`, `ResearchFact`, `ResearchBrief`, `ResearchSource`, `SymbolUniverse`, `CorporateEvent`, `AnalystRating` |

#### Cross-context communication rules (críticas para DDD-lite)

| Rule | Detail |
|---|---|
| NO imports profundos cross-context | `from iguanatrader.contexts.trading.brokers.ibkr_adapter import IBKRAdapter` desde context `risk/` está **prohibido**. Cross-context calls solo via `__init__.py` public API |
| Comunicación cross-context preferida: **MessageBus events** | Context emite event, otros contexts subscribed reaccionan. **Loose coupling** preserved |
| Direct call cross-context permitido SOLO via ports (interfaces) | Si `approval/service.py` necesita info de `trading/`, lo hace via `TradingPort` interface inyectado por kernel |
| Shared primitives: `shared/` | Tipos base (`TenantId`, errors), MessageBus, contextvars. Disponibles para todos los contexts |
| Persistence transversal: cada context tiene su `repository.py` | Pero `session.py` y `tenant_listener.py` viven en `persistence/` (cross-context infrastructure) |
| API delivery: `api/` consume `<context>.service` | Routes son thin: parsing DTO → llamar service → retornar response. NO lógica de negocio en `api/` |

#### Test location

| Type | Location | Convention |
|---|---|---|
| Backend unit | `apps/api/tests/unit/contexts/<context>/test_<module>.py` | Mirror context tree |
| Backend integration | `apps/api/tests/integration/test_<flow>.py` | E2E flows: API → service → repo → DB con mocks brokers/LLM |
| Backend property | `apps/api/tests/property/test_<invariant>.py` | hypothesis tests (RiskEngine never breaches caps) |
| Backend cross-context | `apps/api/tests/integration/test_<flow_cross_contexts>.py` | Verifica interaction patterns (event bus, ports) |
| Frontend unit | `apps/web/src/**/*.test.ts` co-located | Vitest |
| Frontend e2e | `apps/web/tests/*.spec.ts` | Playwright |

### Format Patterns

| Concern | Regla |
|---|---|
| **Money / decimals** | `Decimal` Python (NEVER float), strings JSON (`"612.42"`). Frontend `decimal.js` para arithmetic; `Number()` parse SOLO en formatters de display |
| **Date format** | **ISO 8601 EVERYWHERE** (YYYY-MM-DD o `2026-04-28T14:35:00.123Z` con time UTC). Único formato — sin excepciones. Aplica a: docs markdown prose, frontmatter, JSON wire format, DB columns, structlog timestamps, OTel spans, file names timestampados, Alembic revision IDs, ADR titles |
| Trading session times | US/Eastern explícito en config. Conversión a UTC para storage, a Madrid (Europe/Madrid timezone) para display human |
| IDs | UUID v4 strings (RFC 4122) en JSON: `"550e8400-e29b-41d4-a716-446655440000"`. NEVER auto-increment integers |
| Booleans | Always `true`/`false`, never `1`/`0` |
| Null handling | Optional fields absent vs explicit null: prefer absent. `null` SOLO cuando "no value" tiene meaning distinto a "not set" |
| Arrays | Empty array `[]` para no-results, NUNCA `null` para colecciones |
| Pagination | `{items: [...], total: N, page: N, pageSize: N, hasMore: bool}` para colecciones paginadas. Sin paginar: array directo |
| Single resource response | Direct object `{...}` (no wrapper `{data: {...}}`) |
| Errors | RFC 7807 `application/problem+json`. Lista canónica de error types en `apps/api/src/iguanatrader/api/errors.py` |
| Currency | ISO 4217 code en field separate: `{amount: "100.50", currency: "EUR"}`. NUNCA mixed strings tipo `"100.50€"` |

### Communication Patterns

#### Internal MessageBus events

| Concern | Regla |
|---|---|
| Event naming | `<context>.<entity>.<action>` lowercase dot-separated. Action en past-tense |
| Examples | `trading.proposal.created`, `risk.cap.breached`, `trading.broker.disconnected`, `approval.granted`, `approval.rejected`, `approval.timeout`, `observability.cost.logged`, `risk.kill_switch.activated` |
| Payload | Pydantic models inmutables (`frozen=True`). Hereda de `IguanaEvent` base con `event_id, timestamp, tenant_id, correlation_id` (timestamp ISO 8601) |
| Versioning | In-process events: breaking changes acceptable (single deploy). NO versioning prefix |
| Subscription pattern | `bus.subscribe("trading.proposal.*", handler)` glob patterns |
| Async | All handlers `async def`. Bus dispatch is `await bus.publish(event)` |
| Cross-context purpose | Coupling loose: context A emite, context B reacciona, sin import directo |

#### State management frontend

| Concern | Regla |
|---|---|
| Store factory | Each concern exports `createXxxStore()` factory en `src/lib/stores/<concern>Store.ts` |
| Per-tenant scoping | Tenant context middleware en `hooks.server.ts` injecta tenant_id; stores scoped por tenant via factory |
| Store updates | Svelte 5 runes (`$state`) en stores; setters explícitos via methods (`store.setX()`); NO direct mutation desde components |
| Derived state | `$derived` para computed; no recomputar manualmente |
| SSE consumption | Composable `useEventSource(url)` en `src/lib/composables/`, returns reactive `$state` |

#### Logging conventions

| Concern | Regla |
|---|---|
| API | structlog `logger.info("event_name", field1=val1)`. NEVER f-strings ni `%` formatting |
| Event names | `snake_case.dot.separated` mirror MessageBus events (`trading.proposal.created`, `risk.cap.breached`) |
| Required fields | Auto-injected via contextvars: `tenant_id`, `request_id`, `proposal_id` (when relevant), `strategy`, `symbol`, `event` |
| Sensitive data | NEVER log: passwords, full tokens, full API keys, full prompts (hash via NFR-O7), PII (phone numbers — hash) |
| Levels | DEBUG (dev only), INFO (state transitions), WARNING (recoverable), ERROR (operation failed but system OK), CRITICAL (system-wide impact) |
| Frontend | console.log NO en production. `logger.info()` wrapper que en build prod envía a OTel collector |
| Timestamps | ISO 8601 UTC siempre |

### Process Patterns

#### Error handling

| Layer | Pattern |
|---|---|
| Backend domain errors | Custom hierarchy: `IguanaError` base (`shared/errors.py`) → context-specific subclasses: `RiskCapBreached`, `BrokerDisconnected`, `KillSwitchActive`, `ApprovalTimeout`, `LLMBudgetExceeded` |
| Backend → API conversion | FastAPI exception handler global convierte `IguanaError.<subclass>` → RFC 7807 con `type` URI estable |
| Backend uncaught | structlog ERROR + OTel span error + 500 con generic detail (NO stacktrace al cliente) |
| Frontend route errors | `+error.svelte` per route; logs a OTel client SDK |
| Frontend global | `hooks.client.ts` captura unhandled rejections + window.onerror |
| Validation errors | 422 con RFC 7807 + `errors: [{field, message}]` extension |
| User-facing messages | NEVER expose internal exception text. Mapping table en frontend i18n bundle |

#### Loading states

| Pattern | Regla |
|---|---|
| Initial page load | Skeleton placeholders (Tailwind `animate-pulse`) durante load |
| Action triggers | Inline spinner reemplaza button text + button disabled |
| Optimistic updates | Aplicar para acciones rollback-cheap (config edit, strategy enable/disable). Rollback on error con toast notification |
| Long operations (research_brief refresh, bulk EDGAR ingest) | Progress bar + cancel button + estimated time remaining |
| Streaming SSE | Connection indicator (green dot when connected, red when disconnected with auto-retry countdown) |

#### Authentication flow

| Step | Pattern |
|---|---|
| Login | `POST /api/v1/auth/login` con `{username, password}` → backend valida con argon2 → emite JWT en cookie `iguana_session` (HttpOnly, Secure, SameSite=Strict) → redirect to `/` |
| Authenticated request | Cookie attached automáticamente; FastAPI middleware extrae JWT, valida, populate `tenant_id` contextvar |
| 401 Unauthorized | Frontend interceptor en API client redirect to `/login?next=<original-url>` |
| Logout | `POST /api/v1/auth/logout` → backend clear cookie → redirect to `/login` |
| Session refresh | Sliding window: middleware re-emite JWT con nuevo expiry si <50% lifetime restante. Cookie auto-actualizada |
| Tenant context | JWT claim `tenant_id` → contextvar → propagado a todo el request lifecycle |

#### Validation timing

| Layer | Pattern |
|---|---|
| Frontend immediate | Svelte form validation on input + submit (UX feedback) |
| Frontend on submit | Pre-flight validation con DTO type checks |
| Backend always | Pydantic validation **siempre**, asume frontend bypass-able. NEVER skip server-side validation |
| Domain rules | RiskEngine validates después de Pydantic; rules más profundas (cap breaches, broker constraints) |
| Validation errors | 422 con field-level details |

#### Heartbeat & Reconnect Patterns

Liveness detection es responsabilidad de cada **adapter** (IBKR, Telegram, Hermes/WhatsApp). Pattern uniforme reusable vía `shared/heartbeat.py:HeartbeatMixin`. NO LangGraph (overhead innecesario), NO Hermes (boundary violation).

| Concern | Regla |
|---|---|
| Heartbeat owner | Cada adapter es dueño de su heartbeat. NUNCA centralizar en LangGraph ni en otro adapter |
| Detection mechanism | `asyncio.create_task()` interno al adapter, started en `lifespan` startup, cancelled en shutdown |
| Tick frequency | Configurable per-adapter; defaults: IBKR 30s, Telegram 60s, Hermes 60s |
| Failure threshold | Configurable per-adapter; default `gap > 3 × interval` → emit MessageBus event `<context>.<adapter>.heartbeat_lost` |
| Reconnect policy | `shared/backoff.py:exponential_backoff()` con schedule explícito (default `[3, 6, 12, 24, 48]` segs). Tras N consecutive fails (default 5) → emit `risk.kill_switch.activated` con reason `<adapter>_unreachable` |
| External alerting | Mismo task emite OTel gauge `iguana_<adapter>_heartbeat_last_ts` (UNIX timestamp UTC). Eligia define alerting rule en su repo (no en iguanatrader). **Defense-in-depth**: Capa 1 (in-process) + Capa 2 (Eligia detecta daemon-completely-dead) |
| Idempotency | `heartbeat_lost` event idempotent — dedupe via `last_emitted_lost_at` state; NO emit duplicates si gap continuous |
| Testing | Each adapter MUST tener `tests/integration/test_<adapter>_resilience.py` que simula disconnect window via mock + verifica reconnect schedule |

**Good: HeartbeatMixin usage**

```python
# apps/api/src/iguanatrader/shared/heartbeat.py
class HeartbeatMixin:
    HEARTBEAT_INTERVAL_S: int = 30
    HEARTBEAT_GAP_THRESHOLD_S: int = 90
    BACKOFF_SCHEDULE_S: list[int] = [3, 6, 12, 24, 48]

    async def _heartbeat_loop(self) -> None:
        while not self._shutdown.is_set():
            healthy = await self._ping()
            now = datetime.now(timezone.utc)
            self._metrics.heartbeat_gauge.set(
                now.timestamp(), attributes={"adapter": self.adapter_name}
            )
            if not healthy:
                await self._on_heartbeat_lost(now)
            await asyncio.sleep(self.HEARTBEAT_INTERVAL_S)

    async def _ping(self) -> bool: raise NotImplementedError
    async def _on_heartbeat_lost(self, ts: datetime) -> None: ...

# apps/api/src/iguanatrader/contexts/trading/brokers/ibkr_adapter.py
class IBKRAdapter(HeartbeatMixin, BrokerInterface):
    HEARTBEAT_INTERVAL_S = 30  # NFR-P8
    HEARTBEAT_GAP_THRESHOLD_S = 90  # NFR-P8
    adapter_name = "ibkr"

    async def _ping(self) -> bool:
        return self._ib.isConnected()
```

**Anti-pattern**:

```python
# DON'T: heartbeat as LangGraph node
# Overhead de graph instantiation per tick + LLM-call optimizations no aplican.

# DON'T: heartbeat de IBKR dentro de Hermes
# Boundary violation: Hermes es WhatsApp adapter, no health checker cross-domain.

# DON'T: centralized heartbeat coordinator service
# Single point of failure; cada adapter ya conoce su external service mejor que un coordinator.
```

### Enforcement Guidelines

**All AI Agents (humanos o LLMs) MUST:**

1. Run `make lint` antes de cada commit — pre-commit hook lo enforza
2. Run `make test` — CI bloquea sin esto
3. Use `snake_case` Python end-to-end, `camelCase` JS/TS end-to-end, `camelCase` JSON wire (Pydantic auto-converts)
4. Use `Decimal` para money en Python; strings en JSON; `decimal.js` en TS
5. **NEVER import cross-context profundo**: solo via context `__init__.py` public API o MessageBus events
6. Include `tenant_id` filter en EVERY DB query (event listener enforza)
7. Use structlog `logger.event_name(**fields)` style; never f-strings
8. Use RFC 7807 for all error responses
9. Use `event = "<context>.<entity>.<action>"` naming for MessageBus and logs
10. **Use ISO 8601 UTC en wire/code/logs/docs/ADRs/file-names. Único formato. Sin DD-MM-AA ni alternatives**
11. Update `THIRD_PARTY_NOTICES.md` IF and ONLY IF code copy from external license-required source
12. Use SvelteKit conventions for routes; never custom routing
13. Pattern violations require ADR justifying en `docs/adr/`

**Pattern violation detection:**

- ruff custom rules para naming + cross-context import enforcement (custom check)
- eslint custom rules para naming TS
- mypy strict para type contracts
- pytest snapshot tests para JSON wire format consistency
- pre-commit hook regenera tipos TS desde OpenAPI; CI valida diff = 0
- SQLAlchemy event listener rechaza queries sin tenant_id filter
- Tests de import-graph: each context puede importar SOLO de `shared/` y de su propio context (no cross)

### Pattern Examples

**Good: backend service method (context `risk`)**
```python
# apps/api/src/iguanatrader/contexts/risk/service.py

class RiskService:
    async def evaluate_proposal(
        self,
        proposal: TradeProposal,
        tenant_id: TenantId,  # explicit, even though contextvar exists — defensive
    ) -> RiskEvaluation:
        logger.info("risk.proposal.evaluating", proposal_id=proposal.id)
        result = await self._risk_engine.evaluate(proposal, tenant_id)
        if result.rejected:
            logger.warning(
                "risk.cap.breached",
                proposal_id=proposal.id,
                cap_type=result.cap_type,
                current_pct=str(result.current_pct),  # Decimal as string
            )
            await self._bus.publish(RiskCapBreachedEvent(
                event_id=uuid4(),
                timestamp=datetime.now(timezone.utc),
                tenant_id=tenant_id,
                correlation_id=ctx_correlation_id.get(),
                proposal_id=proposal.id,
                cap_type=result.cap_type,
            ))
        return result
```

**Anti-pattern**:
```python
# DON'T DO THIS
def evaluate(prop):  # no types, no async, no logging, mutable
    if prop.size > 100:  # magic number, no Decimal
        print(f"Rejected {prop}")  # f-string, print, no structlog, no event_name
        return False
    return True
```

**Good: frontend component**
```svelte
<!-- apps/web/src/lib/components/StockRow.svelte -->
<script lang="ts">
  import type { Stock } from '$lib/types';

  interface Props {
    stock: Stock;
    onAction: (s: Stock) => void;
  }

  let { stock, onAction }: Props = $props();
  let isPositive = $derived(stock.changePct > 0);
</script>

<tr class:text-green-500={isPositive} class:text-red-500={!isPositive}>
  <td>{stock.symbol}</td>
  <td>{stock.lastPrice}</td>
  <td>{stock.changePct.toFixed(2)}%</td>
  <td><button onclick={() => onAction(stock)}>Trade</button></td>
</tr>
```

## Project Structure & Boundaries

### Complete Project Directory Structure

```
iguanatrader/                                       # repo root (monorepo)
│
├── README.md                                       # project overview + quickstart
├── LICENSE                                         # Apache-2.0 + Commons Clause
├── THIRD_PARTY_NOTICES.md                          # attribution if external code (initially empty)
├── SECURITY.md                                     # vuln disclosure policy
├── CONTRIBUTING.md                                 # for future OSS contributors (placeholder MVP)
├── CHANGELOG.md                                    # versioned releases
├── Makefile                                        # cross-package commands: test, lint, run-paper, run-live, dashboard
├── pnpm-workspace.yaml                             # pnpm workspace declaration
├── pyproject.toml                                  # Poetry workspace root + dev tooling shared
├── poetry.lock                                     # backend deps lockfile
├── pnpm-lock.yaml                                  # frontend deps lockfile
├── .gitignore                                      # Python + Node + secrets + IDE
├── .gitleaksignore                                 # explicit safe-list for gitleaks
├── .pre-commit-config.yaml                         # gitleaks, ruff, black, mypy, eslint, prettier, openapi-typescript regen
├── .editorconfig                                   # consistent editor settings
│
├── docker-compose.yml                              # base profile dev (default)
├── docker-compose.paper.yml                        # paper trading override (IBKR paper)
├── docker-compose.live.yml                         # live trading override (real money)
├── docker-compose.test.yml                         # CI test environment
│
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                                  # lint + type-check + test + secrets scan, matrix Py 3.11/3.12 + Node 20/22
│   │   ├── build-images.yml                        # Docker image build + push to GHCR
│   │   └── openapi-types.yml                       # ensure regenerated TS types committed
│   └── dependabot.yml                              # manual review (no auto-merge)
│
├── .secrets/                                       # gitignored; SOPS-encrypted at-rest
│   ├── .sops.yaml                                  # age key recipients
│   ├── dev.env.enc                                 # dev secrets (LLM keys, etc.)
│   ├── paper.env.enc                               # paper IBKR creds
│   └── live.env.enc                                # live IBKR creds
│
├── config/                                         # tracked YAML configs
│   ├── iguana.yaml                                 # master: broker, mode, paths, log level
│   ├── risk.yaml                                   # protections + caps (per-trade 2%, daily 5%, weekly 15%, etc.)
│   ├── strategies.yaml                             # per-symbol strategy + params (DonchianATR, SMA Cross)
│   ├── llm_prices.yaml                             # versioned pricing table per provider/model
│   └── slippage.yaml                               # broker slippage models (5-15bps small / 1-3bps large)
│
├── data/                                           # gitignored; runtime
│   ├── iguana.db                                   # SQLite primary
│   ├── iguana.db-wal                               # SQLite WAL
│   ├── iguana.db-shm                               # SQLite shared memory
│   ├── litestream/                                 # backup replicas
│   ├── parquet_cache/                              # historical bars cache
│   │   └── <symbol>/<year>/<month>.parquet
│   ├── research_cache/                             # parquet bars + JSON facts cached per source/symbol
│   └── llm_cache/                                  # LLM call cache TTL-based (key: prompt_hash + model + node + tenant_id)
│       └── <prompt_hash>.json
│
├── logs/                                           # gitignored; structlog rotated JSON
│   └── iguana.YYYY-MM-DD.log
│
├── docs/                                           # all docs
│   ├── prd.md                                      # ✅ EXISTS — sealed, capability contract
│   ├── prd-validation-report.md                    # ✅ EXISTS — PASS, 4.5/5 holistic
│   ├── architecture-decisions.md                   # ⏳ THIS DOCUMENT (in progress)
│   ├── backlog.md                                  # ✅ EXISTS — roadmap v1.0/v1.5/v2/v3
│   ├── runbook.md                                  # extender: deployment, restart, recovery
│   ├── getting-started.md                          # M1: setup local dev
│   ├── architecture.md                             # M1: high-level diagrams (extracto de architecture-decisions.md)
│   ├── strategies/
│   │   ├── donchian_atr.md                         # M1: DonchianATR strategy doc
│   │   ├── sma_cross.md                            # M1: SMA Cross strategy doc
│   │   └── methodology-profiles.md                 # M2: 5 frameworks documentados (3-pillar, CANSLIM, Magic Formula, QARP, Multi-factor)
│   ├── adr/                                        # Architecture Decision Records
│   │   ├── ADR-001-strategy-lifecycle-12-hooks.md
│   │   ├── ADR-002-messagebus-engines-pattern.md
│   │   ├── ADR-003-license-apache-commons-clause.md
│   │   ├── ADR-004-brokerage-model-per-broker.md
│   │   ├── ADR-005-2026-04-28-heartbeat-and-reconnect-patterns.md  # NUEVO 2026-04-28
│   │   ├── ADR-006-risk-engine-declarative-bypass-flow.md
│   │   ├── ADR-007-telegram-whatsapp-channels.md
│   │   ├── ADR-008-per-symbol-strategy-config.md
│   │   ├── ADR-009-mvp-strategies-donchian-sma.md
│   │   ├── ADR-010-ibkr-execution-algos-roadmap.md
│   │   ├── ADR-011-frontend-svelte5-sveltekit.md   # NUEVO post-Party Mode
│   │   ├── ADR-012-ddd-lite-bounded-contexts.md    # NUEVO post-audit
│   │   ├── ADR-013-iso-8601-single-date-format.md  # NUEVO 2026-04-28
│   │   ├── ADR-014-2026-04-28-bitemporal-research-facts.md  # NUEVO Gate A amendment
│   │   ├── ADR-015-2026-04-28-openbb-sidecar-isolation.md   # NUEVO Gate A amendment
│   │   ├── ADR-016-2026-04-28-research-domain-and-backtest-skip.md  # NUEVO Gate A amendment
│   │   ├── ADR-017-2026-04-28-scrape-ladder-4-tiers.md      # NUEVO Gate A amendment
│   │   └── INDEX.md                                # listado consolidado
│   ├── research/                                   # ✅ EXISTS
│   │   ├── oss-algo-trading-landscape.md
│   │   ├── feature-matrix.md
│   │   └── platforms/
│   │       ├── lumibot.md
│   │       ├── nautilustrader.md
│   │       ├── lean.md
│   │       └── freqtrade.md
│   ├── memoria.md                                  # M7: lecciones acumuladas (LLM-generated, human-reviewed)
│   ├── gotchas.md                                  # append-only dev gotchas (NFR-M7 ≥20 entries before MVP close)
│   └── governance.md                               # v2 antes de OSS launch
│
├── apps/
│   ├── api/                                        # ─── PYTHON BACKEND ───
│   │   ├── pyproject.toml                          # backend deps: fastapi, anthropic, ib-async, etc.
│   │   ├── alembic.ini                             # Alembic config
│   │   ├── Dockerfile                              # multi-stage: builder + runtime
│   │   ├── .dockerignore
│   │   ├── conftest.py                             # pytest root: shared fixtures
│   │   │
│   │   ├── src/iguanatrader/
│   │   │   ├── __init__.py                         # package metadata
│   │   │   ├── main.py                             # FastAPI app factory + Kernel boot + lifespan handlers
│   │   │   ├── config.py                           # pydantic-settings 5-layer (CLI > ENV > SOPS > yaml > defaults)
│   │   │   │
│   │   │   ├── shared/                             # ⭐ Cross-context primitives
│   │   │   │   ├── __init__.py                     # exports: TenantId, IguanaError, MessageBus, etc.
│   │   │   │   ├── messagebus.py                   # Pub/Sub bus + IguanaEvent base
│   │   │   │   ├── kernel.py                       # Orchestrator (boots all contexts, wires DI)
│   │   │   │   ├── types.py                        # NewType wrappers: TenantId, ProposalId, OrderId, TradeId, RequestId
│   │   │   │   ├── contextvars.py                  # ContextVar declarations: ctx_tenant_id, ctx_request_id, ctx_correlation_id
│   │   │   │   ├── errors.py                       # IguanaError hierarchy base + subclasses comunes
│   │   │   │   ├── time.py                         # tz utilities (UTC, US/Eastern, Europe/Madrid); ISO 8601 formatters
│   │   │   │   ├── decimal_utils.py                # Decimal helpers for money arithmetic
│   │   │   │   ├── heartbeat.py                    # HeartbeatMixin base + OTel gauge emit (NFR-P8/R7/I2/I5)
│   │   │   │   ├── backoff.py                      # exponential_backoff() primitive (NFR-R7/I2)
│   │   │   │   └── ports.py                        # Cross-context port interfaces (e.g., TradingPort, RiskPort)
│   │   │   │
│   │   │   ├── contexts/                           # ⭐ Bounded contexts (DDD-lite)
│   │   │   │   ├── __init__.py
│   │   │   │   │
│   │   │   │   ├── trading/                        # Strategy + Broker + Trade lifecycle
│   │   │   │   │   ├── __init__.py                 # public API: TradingService, TradeProposal, Strategy, BrokerInterface
│   │   │   │   │   ├── models.py                   # Strategy, TradeProposal, Trade, Order, Fill, Position, Bar
│   │   │   │   │   ├── ports.py                    # BrokerInterface (ABC), BrokerageModel (ABC)
│   │   │   │   │   ├── service.py                  # TradingService: propose, submit, force_exit, reconcile
│   │   │   │   │   ├── repository.py               # TradeRepository, ProposalRepository, OrderRepository, FillRepository
│   │   │   │   │   ├── events.py                   # ProposalCreatedEvent, OrderFilledEvent, BrokerDisconnectedEvent
│   │   │   │   │   ├── strategies/
│   │   │   │   │   │   ├── __init__.py
│   │   │   │   │   │   ├── base.py                 # Strategy ABC con 12-hook lifecycle
│   │   │   │   │   │   ├── donchian_atr.py         # DonchianBreakout + ATR sizing
│   │   │   │   │   │   ├── sma_cross.py            # SMA Cross smoke test
│   │   │   │   │   │   └── manager.py              # StrategyManager: load yaml, hot-reload, per-symbol routing
│   │   │   │   │   └── brokers/
│   │   │   │   │       ├── __init__.py
│   │   │   │   │       ├── ibkr_adapter.py         # IBKRAdapter via ib_async
│   │   │   │   │       └── ibkr_brokerage_model.py # commission + slippage simulation
│   │   │   │   │
│   │   │   │   ├── risk/                           # RiskEngine + Protections
│   │   │   │   │   ├── __init__.py                 # public API: RiskService, RiskEngine, Protection, RiskOverride
│   │   │   │   │   ├── models.py                   # RiskEvaluation, RiskOverride, ProtectionConfig
│   │   │   │   │   ├── engine.py                   # RiskEngine: pure function (proposal, state, config) → RiskEvaluation
│   │   │   │   │   ├── service.py                  # RiskService: orchestrate eval + persist override
│   │   │   │   │   ├── repository.py               # RiskOverrideRepository
│   │   │   │   │   ├── events.py                   # RiskCapBreachedEvent, KillSwitchActivatedEvent
│   │   │   │   │   └── protections/
│   │   │   │   │       ├── __init__.py
│   │   │   │   │       ├── base.py                 # Protection ABC
│   │   │   │   │       ├── per_trade_risk.py       # 2% cap default
│   │   │   │   │       ├── daily_loss_cap.py       # 5% kill-switch
│   │   │   │   │       ├── weekly_loss_cap.py      # 15% kill-switch
│   │   │   │   │       ├── max_open_positions.py
│   │   │   │   │       └── max_drawdown.py
│   │   │   │   │
│   │   │   │   ├── approval/                       # Multi-channel approval gate
│   │   │   │   │   ├── __init__.py                 # public API: ApprovalService, ApprovalChannel
│   │   │   │   │   ├── models.py                   # ApprovalRequest, ApprovalDecision (granted/rejected/timeout)
│   │   │   │   │   ├── ports.py                    # ApprovalChannel ABC
│   │   │   │   │   ├── service.py                  # ApprovalService: fan-out, race resolution, timeout, audit
│   │   │   │   │   ├── repository.py               # ApprovalEventRepository (append-only audit)
│   │   │   │   │   ├── events.py                   # ApprovalGrantedEvent, ApprovalRejectedEvent, ApprovalTimeoutEvent
│   │   │   │   │   └── channels/
│   │   │   │   │       ├── __init__.py
│   │   │   │   │       ├── telegram.py             # python-telegram-bot adapter
│   │   │   │   │       ├── whatsapp_hermes.py      # Hermes/Meta WhatsApp adapter
│   │   │   │   │       └── command_handler.py      # 17 comandos compartidos: /propose, /approve, /halt, etc.
│   │   │   │   │
│   │   │   │   ├── observability/                  # Cost metering + OTel + structlog
│   │   │   │   │   ├── __init__.py                 # public API: CostMeter, OTelExporter
│   │   │   │   │   ├── models.py                   # ApiCostEvent, LLMProvider enum
│   │   │   │   │   ├── cost_meter.py               # Wrapper Anthropic + Perplexity SDKs (NFR-O1)
│   │   │   │   │   ├── perplexity_throttle.py      # Token bucket + queue + drop policy (NFR-I4)
│   │   │   │   │   ├── llm_routing.py              # Multi-model routing: research/routine/alert
│   │   │   │   │   ├── budget.py                   # Daily/weekly LLM budget caps + auto-downgrade
│   │   │   │   │   ├── otel.py                     # OTLP exporter Eligia-compatible
│   │   │   │   │   ├── structlog_config.py         # Processors + contextvars + RotatingFileHandler 100MB/7d (NFR-O3)
│   │   │   │   │   ├── replay_cache.py             # LLM call cache TTL-based (NOT mode-aware; backtest deferred to v1.5+)
│   │   │   │   │   ├── cost_dashboard_publisher.py # 5min consolidated tick to /sse/costs (NFR-O4)
│   │   │   │   │   └── repository.py               # ApiCostEventRepository (append-only)
│   │   │   │   │
│   │   │   │   ├── orchestration/                  # LangGraph routines + cron
│   │   │   │   │   ├── __init__.py                 # public API: OrchestrationService
│   │   │   │   │   ├── models.py                   # Routine, Alert, AlertTier
│   │   │   │   │   ├── service.py                  # OrchestrationService
│   │   │   │   │   ├── scheduler.py                # APScheduler config (cron-jobs Tier 1/2/3)
│   │   │   │   │   ├── alert_filter.py             # Tier 2 LLM-filtered relevance scoring
│   │   │   │   │   ├── tier1_alerts.py             # Tier 1 hardcoded heuristics (event-driven)
│   │   │   │   │   ├── nodes/                      # LangGraph routine nodes
│   │   │   │   │   │   ├── __init__.py
│   │   │   │   │   │   ├── premarket.py            # Pre-market briefing (8:30 ET)
│   │   │   │   │   │   ├── midday.py               # Mid-day check (1 PM ET)
│   │   │   │   │   │   ├── postmarket.py           # Post-market summary (4:30 PM ET)
│   │   │   │   │   │   └── weekly_review.py        # Weekly review LangGraph node (Vie 6 PM ET)
│   │   │   │   │   ├── report_pdf.py                # PDF generator weekly review (FR44) — Plotly+Jinja+WeasyPrint
│   │   │   │   │   └── prompts/                    # versioned markdown LLM prompts
│   │   │   │   │       ├── premarket.md
│   │   │   │   │       ├── midday.md
│   │   │   │   │       ├── postmarket.md
│   │   │   │   │       └── weekly.md
│   │   │   │   │
│   │   │   │   └── research/                       # Research & Intelligence domain (FR57-FR79)
│   │   │   │       ├── __init__.py                 # public API: ResearchService, ResearchPort
│   │   │   │       ├── models.py                   # ResearchFact, ResearchBrief, ResearchSource, SymbolUniverse, CorporateEvent, AnalystRating, WatchlistConfig
│   │   │   │       ├── ports.py                    # ResearchSourcePort, BriefSynthesizerPort
│   │   │   │       ├── service.py                  # ResearchService: ingest, refresh_brief, query_at_time
│   │   │   │       ├── repository.py               # ResearchFactRepository (bitemporal queries), BriefRepository, SourceRepository
│   │   │   │       ├── events.py                   # FactIngestedEvent, BriefRefreshedEvent, MaterialFactArrivedEvent
│   │   │   │       ├── methodology/                # 5 methodology profiles (FR58)
│   │   │   │       │   ├── __init__.py             # MethodologyProfile ABC + registry
│   │   │   │       │   ├── three_pillar.py         # Fundamentals + Macro + Technicals
│   │   │   │       │   ├── canslim.py              # O'Neil CANSLIM (C-A-N-S-L-I-M dimensions)
│   │   │   │       │   ├── magic_formula.py        # Greenblatt: ROC + Earnings Yield
│   │   │   │       │   ├── qarp.py                 # Quality at Reasonable Price (Buffett-style)
│   │   │   │       │   └── multi_factor.py         # Configurable weighted multi-factor
│   │   │   │       ├── synthesis/                  # LLM-driven brief generation
│   │   │   │       │   ├── __init__.py
│   │   │   │       │   ├── synthesizer.py          # Orchestrates fact retrieval → LLM call → brief draft
│   │   │   │       │   ├── citation_resolver.py    # Validates every numeric claim cites a fact (FR70)
│   │   │   │       │   ├── audit_trail.py          # Constructs show-your-work JSON for calculations (FR70)
│   │   │   │       │   └── prompts/                # versioned markdown prompts per methodology
│   │   │   │       │       ├── three_pillar.md
│   │   │   │       │       ├── canslim.md
│   │   │   │       │       ├── magic_formula.md
│   │   │   │       │       ├── qarp.md
│   │   │   │       │       └── multi_factor.md
│   │   │   │       ├── feature_provider/           # Tier system for backtest-safe feature access (FR75)
│   │   │   │       │   ├── __init__.py             # @feature_provider decorator with tier marker
│   │   │   │       │   ├── tier_a.py               # Native PiT: EDGAR XBRL, ALFRED
│   │   │   │       │   ├── tier_b.py               # Snapshot collected: yfinance, Finnhub current, Polygon free
│   │   │   │       │   └── tier_c.py               # One-shot bootstrap: Stooq, MSCI tool
│   │   │   │       ├── sources/                    # Per-source adapters (FR59-FR67)
│   │   │   │       │   ├── __init__.py             # SourceRegistry; registers all by source_id
│   │   │   │       │   ├── sec_edgar.py            # SEC EDGAR via edgartools (FR59 — 10-K/10-Q/8-K/Form4/13F)
│   │   │   │       │   ├── fred.py                 # FRED + ALFRED via fredapi (FR60)
│   │   │   │       │   ├── bls.py                  # BLS API (FR60)
│   │   │   │       │   ├── bea.py                  # BEA API (FR60)
│   │   │   │       │   ├── finnhub.py              # Finnhub free tier: news + sentiment + calendars + ratings (FR61, FR62, FR64)
│   │   │   │       │   ├── gdelt.py                # GDELT DOC 2.0 + BigQuery PESTEL (FR61, FR67)
│   │   │   │       │   ├── openfda.py              # FDA approvals catalysts (FR62)
│   │   │   │       │   ├── openinsider.py          # OpenInsider scraping (FR63 aggregated)
│   │   │   │       │   ├── openbb_sidecar.py       # HTTP client to apps/openbb-sidecar (FR76)
│   │   │   │       │   ├── yfinance_proxy.py       # yfinance via OpenBB sidecar — fundamentals+ratings+ESG (FR64, FR65)
│   │   │   │       │   ├── finviz_scrape.py        # Finviz HTML scrape (Tier 2 ladder)
│   │   │   │       │   ├── wgi_world_bank.py       # WGI governance indicators (FR67)
│   │   │   │       │   ├── vdem.py                 # V-Dem academic dataset CSV (FR67)
│   │   │   │       │   ├── ibkr_bars.py            # IBKR historical bars adapter (FR66 primary)
│   │   │   │       │   ├── yahoo_bars_fallback.py  # Yahoo Finance bars fallback (FR66 secondary)
│   │   │   │       │   ├── hindsight_recall.py     # Hindsight recall (FR81 gated read, NFR-I8 graceful)
│   │   │   │       │   └── hindsight_retain.py     # Hindsight retain (FR80 always-on write)
│   │   │   │       ├── scraping/                   # 4-tier scraping ladder (FR77, FR79)
│   │   │   │       │   ├── __init__.py             # ScrapeLadder abstraction
│   │   │   │       │   ├── tier1_webfetch.py       # httpx + BS4
│   │   │   │       │   ├── tier2_playwright.py     # Chromium headless
│   │   │   │       │   ├── tier3_camoufox.py       # Camoufox MCP stealth Firefox
│   │   │   │       │   ├── tier4_captcha.py        # Camoufox + paid captcha solver
│   │   │   │       │   ├── robots_check.py         # urllib.robotparser programmatic
│   │   │   │       │   └── user_agent.py           # iguanatrader/<version> identifying UA (FR79)
│   │   │   │       └── scheduler.py                # APScheduler config for fact ingestion + brief refresh schedules (FR72)
│   │   │   │
│   │   │   ├── persistence/                        # ⭐ DB infrastructure (cross-context)
│   │   │   │   ├── __init__.py                     # exports: get_session, Base
│   │   │   │   ├── session.py                      # SQLAlchemy session factory + engine config
│   │   │   │   ├── tenant_listener.py              # Event listener: rechaza queries sin tenant_id filter
│   │   │   │   ├── base.py                         # Base SQLModel + naming convention
│   │   │   │   └── migrations/                     # Alembic
│   │   │   │       ├── env.py
│   │   │   │       ├── script.py.mako
│   │   │   │       └── versions/
│   │   │   │           └── <revision>_initial_schema.py
│   │   │   │
│   │   │   ├── api/                                # ⭐ FastAPI delivery layer
│   │   │   │   ├── __init__.py
│   │   │   │   ├── app.py                          # FastAPI factory + middleware + exception handlers
│   │   │   │   ├── auth.py                         # JWT cookie middleware + dependencies
│   │   │   │   ├── deps.py                         # FastAPI Depends: get_tenant_id, get_session, etc.
│   │   │   │   ├── errors.py                       # RFC 7807 exception handlers + error type catalog
│   │   │   │   ├── dtos/                           # Pydantic API DTOs (alias_generator=to_camel)
│   │   │   │   │   ├── __init__.py
│   │   │   │   │   ├── trades.py
│   │   │   │   │   ├── proposals.py
│   │   │   │   │   ├── risk.py
│   │   │   │   │   ├── approvals.py
│   │   │   │   │   ├── costs.py
│   │   │   │   │   ├── strategies.py
│   │   │   │   │   ├── research.py                 # ResearchBriefDTO, ResearchFactDTO, WatchlistConfigDTO, AuditTrailDTO
│   │   │   │   │   ├── auth.py
│   │   │   │   │   └── common.py                   # Pagination, ErrorEnvelope (RFC 7807)
│   │   │   │   ├── routes/                         # /api/v1/* JSON endpoints
│   │   │   │   │   ├── __init__.py
│   │   │   │   │   ├── auth.py                     # /api/v1/auth/*
│   │   │   │   │   ├── trades.py                   # /api/v1/trades
│   │   │   │   │   ├── approvals.py                # /api/v1/approvals
│   │   │   │   │   ├── risk.py                     # /api/v1/risk + risk-overrides
│   │   │   │   │   ├── strategies.py               # /api/v1/strategies + per-symbol config
│   │   │   │   │   ├── portfolio.py                # /api/v1/portfolio
│   │   │   │   │   ├── costs.py                    # /api/v1/costs
│   │   │   │   │   ├── research.py                 # /api/v1/research/* (briefs, facts, watchlist, sources)
│   │   │   │   │   ├── settings.py                  # /api/v1/settings/feature-flags (admin role only) — FR81 toggle
│   │   │   │   │   └── ops.py                      # /api/v1/halt, /resume, /reload-config, /override
│   │   │   │   └── sse/                            # /api/v1/sse/* event streams
│   │   │   │       ├── __init__.py
│   │   │   │       ├── equity.py                   # /sse/equity (fill events)
│   │   │   │       ├── approvals.py                # /sse/approvals (queue updates)
│   │   │   │       ├── risk.py                     # /sse/risk (cap state changes)
│   │   │   │       ├── costs.py                    # /sse/costs (real-time + 5min tick, NFR-O4)
│   │   │   │       ├── research.py                 # /sse/research (BriefRefreshedEvent, MaterialFactArrivedEvent push)
│   │   │   │       └── alerts.py                   # /sse/alerts (Tier 1+2)
│   │   │   │
│   │   │   └── cli/                                # ⭐ typer CLI surface
│   │   │       ├── __init__.py
│   │   │       ├── main.py                         # iguana CLI app + version
│   │   │       ├── init.py                         # iguana init
│   │   │       ├── ingest.py                       # iguana ingest bars <symbol>
│   │   │       ├── research.py                     # iguana research refresh|show|list <symbol>
│   │   │       ├── paper.py                        # iguana paper (daemon)
│   │   │       ├── live.py                         # iguana live (daemon, requires --confirm-live --i-understand-the-risks per AGENTS.md §7 Override 1)
│   │   │       ├── dashboard.py                    # iguana dashboard (daemon)
│   │   │       ├── propose.py                      # iguana propose <strategy> <symbol>
│   │   │       ├── ops.py                          # iguana halt / resume / reload-config / override
│   │   │       ├── export.py                       # iguana export trades / risk-overrides
│   │   │       ├── strategies.py                   # iguana strategies list/enable/disable/set-param
│   │   │       ├── settings.py                     # iguana settings feature-flag <name> <enable|disable>
│   │   │       └── retain.py                       # iguana retain (Hindsight memory bridge)
│   │   │
│   │   └── tests/
│   │       ├── conftest.py                         # global fixtures (mock broker, mock LLM, in-memory DB)
│   │       ├── unit/
│   │       │   └── contexts/
│   │       │       ├── trading/test_strategies.py
│   │       │       ├── trading/test_brokers.py
│   │       │       ├── risk/test_engine.py
│   │       │       ├── risk/test_protections.py
│   │       │       ├── approval/test_service.py
│   │       │       ├── approval/test_channels.py
│   │       │       ├── observability/test_cost_meter.py
│   │       │       ├── orchestration/test_scheduler.py
│   │       │       ├── research/test_bitemporal_queries.py    # what did we know at T?
│   │       │       ├── research/test_provenance_enforcement.py # missing source_id raises
│   │       │       ├── research/test_audit_trail_render.py    # show-your-work JSON valid
│   │       │       ├── research/test_methodology_profiles.py  # all 5 frameworks
│   │       │       ├── research/test_feature_provider_tier.py # A/B/C tier markers + None handling
│   │       │       ├── research/test_citation_resolver.py     # broken citations fail render
│   │       │       └── research/test_scrape_ladder.py         # 4-tier escalation
│   │       ├── integration/
│   │       │   ├── test_proposal_to_fill_flow.py   # E2E: signal → research_brief → risk → approval → submit → fill
│   │       │   ├── test_risk_override_flow.py      # E2E: rejected → override → audit
│   │       │   ├── test_kill_switch_flow.py        # E2E: trigger via 4 sources
│   │       │   ├── test_reconciliation.py          # broker↔cache reconcile post-disconnect
│   │       │   ├── test_research_brief_refresh.py  # E2E: ingest facts (EDGAR+FRED+news) → synthesize → render with citations
│   │       │   ├── test_openbb_sidecar_health.py   # HTTP loopback healthcheck + heartbeat
│   │       │   ├── test_cross_tenant_isolation.py  # tenant_id enforcement
│   │       │   ├── test_ibkr_resilience.py         # disconnect→backoff→kill-switch (NFR-R7/I2/P8)
│   │       │   ├── test_telegram_resilience.py     # long-polling reconnect + queue persist (NFR-I5)
│   │       │   ├── test_hermes_resilience.py       # Hermes/WhatsApp adapter heartbeat
│   │       │   └── test_perplexity_throttle.py     # rate limit + queue + drop policy (NFR-I4)
│   │       ├── property/
│   │       │   ├── test_risk_caps_invariant.py     # hypothesis: never breach
│   │       │   ├── test_decimal_arithmetic.py      # money arithmetic invariants
│   │       │   ├── test_strategy_no_lookahead.py   # on_bar(t) cannot access t+1
│   │       │   └── test_message_ordering.py        # MessageBus event ordering
│   │       └── fixtures/
│   │           ├── historical_bars/                # parquet fixtures
│   │           ├── llm_replay_cache/               # cached LLM responses
│   │           └── ibkr_mock_responses/            # mock broker responses
│   │
│   └── web/                                        # ─── SVELTEKIT FRONTEND ───
│       ├── package.json
│       ├── pnpm-lock.yaml
│       ├── svelte.config.js
│       ├── vite.config.ts
│       ├── tsconfig.json
│       ├── tailwind.config.ts
│       ├── postcss.config.cjs
│       ├── playwright.config.ts
│       ├── eslint.config.js
│       ├── prettier.config.js
│       ├── Dockerfile                              # Node builder + Nginx serve assets
│       ├── .dockerignore
│       │
│       ├── src/
│       │   ├── app.html                            # SvelteKit shell
│       │   ├── app.css                             # Tailwind base + globals
│       │   ├── app.d.ts                            # global types
│       │   ├── hooks.server.ts                     # auth middleware, tenant context
│       │   ├── hooks.client.ts                     # global error → OTel
│       │   │
│       │   ├── routes/                             # file-based routing
│       │   │   ├── +layout.svelte                  # root layout (nav, theme)
│       │   │   ├── +layout.ts                      # root load (auth check)
│       │   │   ├── +page.svelte                    # / (equity curve + drawdown + positions + kill-switch)
│       │   │   ├── +error.svelte                   # global error boundary
│       │   │   ├── (auth)/
│       │   │   │   └── login/
│       │   │   │       ├── +page.svelte
│       │   │   │       └── +page.server.ts         # form action: POST /api/v1/auth/login
│       │   │   └── (app)/                          # authenticated route group
│       │   │       ├── +layout.svelte              # authenticated layout
│       │   │       ├── +layout.server.ts           # tenant resolution
│       │   │       ├── approvals/
│       │   │       │   ├── +page.svelte            # cola pending + history
│       │   │       │   └── +page.server.ts         # load pending + setup SSE
│       │   │       ├── trades/
│       │   │       │   ├── +page.svelte            # filterable history
│       │   │       │   └── +page.server.ts
│       │   │       ├── portfolio/
│       │   │       │   ├── +page.svelte
│       │   │       │   └── +page.server.ts
│       │   │       ├── costs/
│       │   │       │   ├── +page.svelte            # USD/día + per-node + cost-per-trade ratio
│       │   │       │   └── +page.server.ts
│       │   │       ├── risk/
│       │   │       │   ├── +page.svelte            # caps state + override audit + kill-switch
│       │   │       │   └── +page.server.ts
│       │   │       ├── research/
│       │   │       │   ├── +page.svelte            # watchlist + per-symbol research_brief overview
│       │   │       │   ├── +page.server.ts
│       │   │       │   └── [symbol]/
│       │   │       │       ├── +page.svelte        # symbol detail: brief vigente + facts timeline + citations
│       │   │       │       ├── +page.server.ts
│       │   │       │       └── audit-trail/[brief_version]/
│       │   │       │           ├── +page.svelte    # show-your-work view per calculation
│       │   │       │           └── +page.server.ts
│       │   │       └── settings/
│       │   │           ├── +page.svelte            # tenant settings: feature flags toggles (Hindsight recall + future)
│       │   │           └── +page.server.ts         # admin-role gated; PATCH /api/v1/settings/feature-flags
│       │   │
│       │   ├── lib/
│       │   │   ├── api/
│       │   │   │   ├── client.ts                   # fetch wrapper + interceptors (401 redirect, error parsing)
│       │   │   │   ├── auth.ts                     # login/logout calls
│       │   │   │   ├── trades.ts                   # trade endpoints
│       │   │   │   ├── approvals.ts
│       │   │   │   ├── risk.ts
│       │   │   │   ├── strategies.ts
│       │   │   │   ├── portfolio.ts
│       │   │   │   ├── costs.ts
│       │   │   │   ├── research.ts                  # GET briefs / facts / watchlist / sources
│       │   │   │   └── ops.ts
│       │   │   │
│       │   │   ├── components/
│       │   │   │   ├── EquityCurve.svelte          # TradingView Lightweight Charts wrapper
│       │   │   │   ├── DrawdownGauge.svelte
│       │   │   │   ├── PositionsTable.svelte
│       │   │   │   ├── ApprovalCard.svelte         # proposal con countdown + buttons
│       │   │   │   ├── ApprovalList.svelte
│       │   │   │   ├── TradesTable.svelte
│       │   │   │   ├── CostBreakdownChart.svelte   # ApexCharts USD/día per provider
│       │   │   │   ├── RiskCapsBar.svelte          # cap consumption visual
│       │   │   │   ├── KillSwitchButton.svelte     # big red button con confirm
│       │   │   │   ├── OverrideForm.svelte         # reason ≥20 chars + double confirm
│       │   │   │   ├── StockRow.svelte             # streaming row con animate:flip
│       │   │   │   ├── ConnectionIndicator.svelte  # SSE status (green/red)
│       │   │   │   ├── SkeletonLoader.svelte
│       │   │   │   ├── Toast.svelte
│       │   │   │   └── nav/Sidebar.svelte
│       │   │   │
│       │   │   ├── stores/
│       │   │   │   ├── tenantStore.ts              # current tenant context
│       │   │   │   ├── authStore.ts                # session state
│       │   │   │   ├── equityStore.ts              # SSE-fed equity ticks
│       │   │   │   ├── approvalsStore.ts           # SSE-fed approval queue
│       │   │   │   ├── riskStore.ts                # SSE-fed cap state
│       │   │   │   ├── alertsStore.ts              # Tier 1+2 alerts
│       │   │   │   ├── connectionStore.ts          # SSE connection state
│       │   │   │   └── themeStore.ts               # light/dark
│       │   │   │
│       │   │   ├── composables/
│       │   │   │   ├── useEventSource.ts           # SSE consumer
│       │   │   │   ├── useCountdown.ts             # approval timeout countdown
│       │   │   │   └── useFormatPrice.ts           # decimal.js formatter
│       │   │   │
│       │   │   ├── utils/
│       │   │   │   ├── format.ts                   # date, number, percent formatters (ISO 8601 → display)
│       │   │   │   ├── decimal.ts                  # decimal.js wrappers
│       │   │   │   └── tz.ts                       # timezone conversions
│       │   │   │
│       │   │   ├── types/
│       │   │   │   └── index.ts                    # re-exports from packages/shared-types
│       │   │   │
│       │   │   ├── i18n/                           # placeholder MVP, populate v3
│       │   │   │   ├── en.json
│       │   │   │   └── es.json
│       │   │   │
│       │   │   └── icons/                          # SVG components
│       │   │
│       │   └── service-worker.ts                   # PWA-ready, disabled MVP
│       │
│       ├── static/
│       │   ├── favicon.svg
│       │   ├── robots.txt
│       │   └── manifest.webmanifest                # PWA manifest, activated v2
│       │
│       └── tests/
│           ├── e2e/
│           │   ├── auth.spec.ts                    # login flow
│           │   ├── approval-flow.spec.ts           # propose → approve → fill (Journey 1)
│           │   ├── override-flow.spec.ts           # cap rejected → override → audit (Journey 2)
│           │   ├── weekly-review.spec.ts           # PDF generation (Journey 3)
│           │   └── failure-recovery.spec.ts        # disconnect + reconcile (Journey 4)
│           └── fixtures/
│
└── packages/
    └── shared-types/                               # ─── AUTO-GENERATED TS TYPES ───
        ├── package.json
        ├── tsconfig.json
        ├── src/
        │   ├── index.ts                            # re-exports
        │   └── generated.ts                        # ⚠️ AUTO-GENERATED via openapi-typescript; do NOT edit manually
        └── README.md                               # how regenerate (pnpm run generate-types)
```

### Architectural Boundaries

#### API boundaries (external)

| Endpoint group | Path prefix | Auth | Purpose |
|---|---|---|---|
| Authentication | `/api/v1/auth/*` | None (login) / Cookie (others) | Login, logout, session refresh |
| Trading | `/api/v1/trades`, `/api/v1/proposals` | Cookie | Read trade history, list proposals |
| Approvals | `/api/v1/approvals` | Cookie | Approve/reject pending |
| Risk | `/api/v1/risk`, `/api/v1/risk-overrides` | Cookie | Read caps state, audit overrides |
| Strategies | `/api/v1/strategies` | Cookie | List, enable/disable, set-param per symbol |
| Portfolio | `/api/v1/portfolio` | Cookie | P&L, holdings, positions |
| Costs | `/api/v1/costs` | Cookie | LLM cost dashboard data |
| Research | `/api/v1/research/briefs/{symbol}`, `/api/v1/research/briefs/{id}/audit-trail`, `/api/v1/research/facts/{symbol}`, `/api/v1/research/watchlist`, `/api/v1/research/sources` | Cookie | Read brief vigente or specific version, query facts bitemporally (`as_of` query param), manage watchlist, list source health |
| Operations | `/api/v1/halt`, `/api/v1/resume`, `/api/v1/reload-config`, `/api/v1/override` | Cookie | Ops actions |
| **SSE streams** | `/api/v1/sse/equity`, `/sse/approvals`, `/sse/risk`, `/sse/alerts` | Cookie | Server push event streams |
| OpenAPI docs | `/api/docs`, `/api/redoc` | None (dev only; disabled prod or auth-gated) | API documentation |

#### Component boundaries (internal)

| Boundary | Pattern |
|---|---|
| `api/routes/` ↔ `contexts/<context>/service.py` | Direct call. Routes thin: parse DTO → call service → return DTO |
| `contexts/<A>/` ↔ `contexts/<B>/` | **Indirect via MessageBus events OR ports** — never direct import |
| `contexts/<context>/service.py` ↔ `contexts/<context>/repository.py` | Service inyecta repository |
| `contexts/<context>/repository.py` ↔ DB | Via SQLAlchemy session (inyectada) + tenant_listener enforcement |
| `shared/messagebus.py` ↔ all contexts | Bus-as-singleton inyectado por Kernel |
| `apps/web/` ↔ `apps/api/` | Solo HTTPS REST + SSE; tipos compartidos vía `packages/shared-types/` |
| `apps/web/src/lib/api/` ↔ `apps/web/src/routes/` | Routes use load functions que llaman api client |
| `cli/` ↔ contexts | Direct calls a context services (no via API HTTP — same process) |

#### Data boundaries

| Layer | Responsibility |
|---|---|
| **DB tables (per context)** | Each context owns its tables. NO cross-context DB queries. Cross-context data access via service calls or events. |
| **`tenant_id` enforcement** | SQLAlchemy event listener (en `persistence/tenant_listener.py`) rechaza queries sin filter. Globally enforced. |
| **Configs (`config/*.yaml`)** | Owned by `config.py` pydantic-settings. Loaded once at startup; hot-reloadable via `/reload-config`. |
| **Research cache (`data/research_cache/`, `data/parquet_cache/`)** | Owned by `contexts/research/sources/<source>.py` adapters. Read-write per source. Bitemporal queries served from `research_facts` SQLite table; raw payloads pointed via `raw_payload_path` to parquet/JSON files. |
| **LLM cache (`data/llm_cache/`)** | Owned by `observability/replay_cache.py`. TTL-based, no longer mode-aware (Gate A amendment 2026-04-28). Cache key: `(prompt_hash, model, node, tenant_id)`. |
| **Logs (`logs/`)** | Owned by `observability/structlog_config.py`. Append-only rotated files. |

### Requirements to Structure Mapping

| FR cluster | Files / locations |
|---|---|
| **FR1-FR5 Strategy Management** | `contexts/trading/strategies/`, `contexts/trading/__init__.py`, `api/routes/strategies.py`, `cli/strategies.py`, `web/src/routes/(app)/strategies/` (v1.5+) |
| ~~FR6-FR10 Backtest & Research~~ | REMOVED 2026-04-28 (Gate A amendment) |
| **FR57-FR79 Research & Intelligence Domain** | `contexts/research/` completo (methodology/, synthesis/, feature_provider/, sources/, scraping/, scheduler.py), `cli/research.py`, `cli/ingest.py`, `api/routes/research.py`, `api/sse/research.py`, `web/src/routes/(app)/research/<symbol>/`, `apps/openbb-sidecar/` (FR76 isolation) |
| **FR11-FR18 Trade Lifecycle** | `contexts/trading/service.py`, `contexts/trading/brokers/`, `contexts/trading/repository.py`, `api/routes/trades.py`, `api/sse/equity.py`, `web/src/routes/(app)/trades/` |
| **FR19-FR30 Risk Management** | `contexts/risk/`, `config/risk.yaml`, `api/routes/risk.py`, `api/sse/risk.py`, `web/src/routes/(app)/risk/`, `tests/property/test_risk_caps_invariant.py` |
| **FR31-FR38 Notifications & HITL** | `contexts/approval/`, `config/iguana.yaml` (authorized lists), `api/routes/approvals.py`, `api/sse/approvals.py`, `web/src/routes/(app)/approvals/` |
| **FR39-FR45 LLM Orchestration & Cost** | `contexts/observability/{cost_meter,perplexity_throttle,llm_routing,budget,cost_dashboard_publisher}.py`, `contexts/orchestration/{nodes/weekly_review.py,report_pdf.py}` (FR44 PDF generator), `config/llm_prices.yaml`, `api/routes/costs.py`, `api/sse/costs.py` (NFR-O4), `web/src/routes/(app)/costs/` |
| **FR46-FR51 Data, Persistence & Audit** | `persistence/`, `contexts/<each>/repository.py`, `contexts/<each>/events.py`, `cli/export.py`, `api/routes/*` (export endpoints) |
| **FR52-FR56 Operational Surface** | `cli/`, `api/routes/ops.py`, `web/src/routes/(app)/` (dashboard pages), `Makefile` |

### Integration Points

#### Internal communication

```
[CLI / Web UI / SSE]
        │
        ▼
[FastAPI routes (api/)] ─── thin parsing, delegates to ───▶
        │
        ▼
[Context services (contexts/<X>/service.py)]
        │
        ├─── Direct call (same context) ───▶ Repository → DB
        │
        ├─── Cross-context need ───▶ MessageBus.publish(event) ───▶ subscribed handlers in other contexts
        │
        └─── Cross-context direct (rare) ───▶ Port (interface) ─── inyectado por Kernel ───▶ Other context's service
```

#### External integrations

| External | Adapter location | Protocol |
|---|---|---|
| IBKR (broker) | `contexts/trading/brokers/ibkr_adapter.py` (HeartbeatMixin + backoff [3,6,12,24,48]) | TWS Gateway socket via `ib_async` |
| Anthropic (LLM) | `contexts/observability/cost_meter.py` (wrapper) → SDK | HTTPS REST |
| Perplexity (news) | `contexts/observability/cost_meter.py` (wrapper) + `perplexity_throttle.py` (token bucket) → SDK | HTTPS REST |
| Telegram | `contexts/approval/channels/telegram.py` (HeartbeatMixin) | python-telegram-bot long-polling + auto-reconnect |
| WhatsApp Meta | `contexts/approval/channels/whatsapp_hermes.py` (HeartbeatMixin) | HTTPS to Hermes service |
| Yahoo Finance (bars + fundamentals snapshot) | `contexts/research/sources/yfinance_proxy.py` via `apps/openbb-sidecar/` HTTP loopback | HTTPS through sidecar |
| SEC EDGAR (10-K/10-Q/8-K/Form4/13F) | `contexts/research/sources/sec_edgar.py` (`edgartools` lib) | HTTPS REST, official APIs |
| FRED + ALFRED (macro PiT) | `contexts/research/sources/fred.py` (`fredapi`) | HTTPS REST |
| BLS / BEA (macro) | `contexts/research/sources/{bls,bea}.py` | HTTPS REST |
| Finnhub (news/sentiment/calendars/ratings free tier) | `contexts/research/sources/finnhub.py` | HTTPS REST |
| GDELT (news + PESTEL) | `contexts/research/sources/gdelt.py` (DOC 2.0 + BigQuery for events) | HTTPS REST + BigQuery |
| openFDA (drug approvals catalysts) | `contexts/research/sources/openfda.py` | HTTPS REST |
| OpenInsider (insider screens) | `contexts/research/sources/openinsider.py` (Tier 1 scraping) | HTTPS HTML scrape |
| Finviz (analyst ratings supplement) | `contexts/research/sources/finviz_scrape.py` (Tier 2 scraping) | HTTPS HTML scrape |
| WGI / V-Dem (governance/PESTEL academic) | `contexts/research/sources/{wgi_world_bank,vdem}.py` | CSV download via HTTPS |
| OpenBB Platform (aggregator sidecar) | `contexts/research/sources/openbb_sidecar.py` HTTP client | HTTP `localhost:8765` (AGPL boundary preserved per FR76) |
| IBKR historical bars | `contexts/research/sources/ibkr_bars.py` (primary FR66) | TWS Gateway socket via `ib_async` |
| Eligia OTel collector | `contexts/observability/otel.py` | OTLP gRPC/HTTP |
| Hindsight bank `iguanatrader-research-<tenant>` | `contexts/research/sources/hindsight_recall.py` (read, FR81 gated) + `contexts/research/sources/hindsight_retain.py` (write, FR80 always-on) | HTTP MCP, semantic recall (write always; read togglable per-tenant via `tenants.feature_flags.hindsight_recall_enabled`) |

### Data Flow

#### Critical path: trade proposal → fill

```
1. Strategy (contexts/trading/strategies/donchian_atr.py).on_bar(bar)
2. Strategy emits proposal → MessageBus event "trading.proposal.draft"
3. RiskService (contexts/risk/service.py) subscriber recibe → RiskEngine.evaluate()
4. Si RiskEngine.allow → ApprovalService (contexts/approval/service.py) recibe
5. ApprovalService.fan_out_to_channels() → Telegram + WhatsApp en paralelo
6. User responde en algún channel → ApprovalChannel.on_response()
7. ApprovalService persist decision → emit "approval.granted"
8. TradingService (contexts/trading/service.py) subscriber → BrokerInterface.submit_order()
9. IBKRAdapter envía a TWS Gateway → broker confirma fill
10. Fill event → MessageBus "trading.order.filled"
11. Múltiples subscribers reaccionan:
   - TradingRepository persist Fill (append-only)
   - SSE /sse/equity push event a frontend
   - ObservabilityService log + OTel span
   - RiskService recalcula cap state
```

#### Critical path: research_brief synthesis with provenance + show-your-work + Hindsight integration

```
1. Trigger: scheduler.refresh_brief(symbol="AAPL") OR MaterialFactArrivedEvent (e.g. 8-K filing detected)
2. ResearchService.refresh_brief("AAPL") → orchestrates:
   a. SourceRegistry parallel fetch: edgartools (XBRL financials), fredapi (macro), finnhub (news+sentiment),
      openfda (FDA catalysts), openinsider (insider screens), openbb_sidecar HTTP (yfinance proxy + ESG)
   b. Each adapter.fetch() returns list[ResearchFact] with mandatory provenance
      (source_id, source_url, retrieval_method, retrieved_at)
   c. ResearchFactRepository.persist_bitemporal(facts) — insert with effective_from = published_at,
      recorded_from = retrieved_at; CHECK constraints reject incomplete provenance
3. methodology = WatchlistConfig(tenant_id, symbol).methodology  # e.g. 'three_pillar'
4. ⭐ NEW: Conditional Hindsight recall (FR81 gated):
   if tenant.feature_flags.hindsight_recall_enabled (default FALSE; user toggles in dashboard settings):
       try:
           hindsight_context = await hindsight_recall.recall(
               bank=f"iguanatrader-research-{tenant_id}",
               query=f"{symbol} fundamentals macro context lessons",
               limit=20, timeout_ms=2000
           )  # NFR-I8: p50 < 500ms, p95 < 2s, graceful failure
       except (HindsightUnavailable, HindsightTimeout):
           logger.warning("research.hindsight.recall_failed", symbol=symbol)
           hindsight_context = []  # graceful degradation — no block
   else:
       hindsight_context = []  # toggle OFF — baseline synthesis
5. Synthesizer.synthesize(symbol, facts, hindsight_context, methodology) →
   - LLM call (Anthropic SDK with prompt caching for stable system prompt)
   - Prompt: (system) + (research_facts current PiT) + (hindsight narrative if enabled) + (methodology)
   - LLM output parsed into ResearchBrief draft with [fact_id] citations inline
6. CitationResolver.validate(draft) — every numeric claim MUST cite a fact_id;
   broken citations → render fails (CI-blocking) or soft-fail with warning (live, NFR-O8)
7. AuditTrailBuilder.compute_calculations(draft) — for each calculated metric (P/E, growth %, ratios):
   build {formula, inputs[fact_id+value], steps, output} JSON
8. ResearchBriefRepository.persist(brief, version=N+1, hindsight_recalled=<bool>) — immutable
9. ⭐ NEW: Always-on Hindsight write (FR80, no toggle):
   await hindsight_retain.retain(
       bank=f"iguanatrader-research-{tenant_id}",
       kind="brief_summary",
       content=brief.thesis + brief.key_insights,
       metadata={"brief_id": brief.id, "symbol": symbol, "version": brief.version}
   )  # builds narrative history from day 1; if down, log + continue
10. MessageBus.publish(BriefRefreshedEvent) → /sse/research push to frontend
11. CostMeter logs ApiCostEvent with cache_hit_tokens (NFR-I3 prompt caching observability)
```

### File Organization Patterns (consolidado)

| Concern | Pattern |
|---|---|
| Configuration | `config/*.yaml` versionado + `.secrets/*.enc` SOPS-encrypted (gitignored) |
| Source organization | `apps/api/src/iguanatrader/contexts/<context>/{models,ports,service,repository,events}.py` + sub-dirs cuando aplique |
| Test organization | `apps/api/tests/{unit,integration,property,fixtures}/` mirror context tree |
| Static assets | `apps/web/static/` + `apps/web/src/lib/icons/` |
| Documentation | `docs/{adr/,research/,strategies/}` per topic + flat docs root |
| Build outputs | `apps/api/dist/` + `apps/web/build/` (gitignored) |
| Runtime data | `data/` + `logs/` (gitignored, mounted volumes en Docker) |

### Development Workflow Integration

| Stage | Commands / files |
|---|---|
| First-time setup | `make bootstrap` → `poetry install` + `pnpm install` + decrypt secrets + run migrations |
| Dev loop backend | `make dev-api` → uvicorn hot-reload on `localhost:8000` |
| Dev loop frontend | `make dev-web` → vite hot-reload on `localhost:5173` (proxies API to 8000) |
| Test all | `make test` → pytest backend + vitest frontend + playwright e2e |
| Lint all | `make lint` → ruff + black + mypy + eslint + prettier + svelte-check |
| Build images | `make build-images` → docker buildx para api + web |
| Run paper | `make run-paper` → docker compose -f docker-compose.yml -f docker-compose.paper.yml up |
| Run live | `make run-live` → docker compose -f docker-compose.yml -f docker-compose.live.yml up (con `--confirm-live`) |
| Generate types | `make generate-types` → openapi-typescript consumes FastAPI OpenAPI → packages/shared-types/src/generated.ts |
| Backup test | `make backup-test` → litestream verify + restore dry-run |

## Architecture Validation Results

### Coherence Validation

#### Decision Compatibility

Todas las decisiones tech encajan sin conflicto. Stack 100% probado en 2026:

- **Python 3.11+ + asyncio + FastAPI + SQLAlchemy + sqlmodel**: combo maduro, sin version pin conflicts conocidos.
- **Svelte 5 + SvelteKit 2.x + Vite 5 + Tailwind 4.x + TypeScript 5.x strict**: Svelte 5 estable desde 2024-Q4; sin issue compatibility con SvelteKit 2.x.
- **pnpm workspace + Poetry workspace**: ambos workspace managers operan sobre subsets disjuntos de archivos (`*.py` vs `*.{ts,svelte}`); sin colisión.
- **SQLite WAL + litestream**: combo recomendado oficialmente (litestream replica WAL stream).
- **structlog + OTel**: structlog processor adicional emite OTLP — patrón estándar.
- **Argon2id + JWT cookie + SameSite=Strict + slowapi**: todas crypto/security primitives current best practice 2026.
- **HeartbeatMixin + asyncio + OTel gauges**: pattern uniforme reusable; cero deps nuevas.

#### Pattern Consistency

Patterns alineados con tech stack:

- **DDD-lite contexts** mapean clean a Python packages con `__init__.py` public API enforcement.
- **Repository pattern** alineado con SQLAlchemy + sqlmodel (idiomatic).
- **MessageBus** in-process async coherente con asyncio single-loop decision (NFR-R1).
- **OpenAPI → openapi-typescript pipeline** alineado con FastAPI built-in OpenAPI generation.
- **Naming conventions** (snake_case backend, camelCase frontend, camelCase JSON wire) consistentes con Pydantic `alias_generator=to_camel`.
- **Heartbeat ownership pattern**: cada adapter dueño de su liveness check vía mixin shared; defense-in-depth con Eligia.

#### Structure Alignment

Estructura `apps/api/src/iguanatrader/contexts/<context>/` soporta:

- DDD-lite cross-context rules (NO imports profundos enforced via test de import-graph).
- Test mirror tree (`tests/unit/contexts/<context>/`) + resilience tests (`tests/integration/test_<adapter>_resilience.py`).
- Bus factor 1: dev nuevo encuentra todo lo de "trading" bajo `contexts/trading/` sin saltar entre layers.
- Multi-tenant ready: `tenant_id` enforcement vive en `persistence/tenant_listener.py` aplicado a TODOS los contexts uniformemente.
- Liveness primitives en `shared/{heartbeat,backoff}.py` reutilizables por cualquier adapter externo.

### Requirements Coverage Validation

#### Functional Requirements Coverage (56/56)

| Cluster | FRs cubiertos | Locations principales |
|---|---|---|
| Strategy Management (FR1-FR5) | 5/5 | `contexts/trading/strategies/manager.py` (hot-reload), `config/strategies.yaml`, `cli/strategies.py`, `api/routes/strategies.py` |
| ~~Backtest & Research (FR6-FR10)~~ | REMOVED 2026-04-28 (Gate A amendment) | n/a |
| **Research & Intelligence Domain (FR57-FR79)** | 23/23 | `contexts/research/` completo (methodology/, synthesis/, feature_provider/, sources/, scraping/, scheduler.py); `apps/openbb-sidecar/` AGPL-isolated; `cli/research.py`; `api/routes/research.py` + `api/sse/research.py`; `web/src/routes/(app)/research/<symbol>/`; integration tests `test_research_brief_refresh.py` + `test_openbb_sidecar_health.py`; unit tests bitemporal queries + provenance + audit_trail + methodologies + tier system + citations + scrape ladder |
| Trade Lifecycle (FR11-FR18) | 8/8 | `contexts/trading/{service,brokers}/` + `BrokerInterface` ABC (FR14) + reconciliation (FR16) + `force_exit`/`force_create` en service (FR17/FR18) |
| Risk Management (FR19-FR30) | 12/12 | `contexts/risk/protections/` (FR19-FR23, FR27 master, FR28 selective), `service.py` (FR24-FR26), kill-switch global flag (FR29-FR30) |
| Notifications & HITL (FR31-FR38) | 8/8 | `contexts/approval/channels/{telegram,whatsapp_hermes}` (HeartbeatMixin) + `command_handler.py` (17 commands shared, FR37), fan-out paralelo (FR32), whitelist en `config/iguana.yaml` (FR31, FR38) |
| LLM Orchestration & Cost (FR39-FR45) | 7/7 | `contexts/observability/{cost_meter,perplexity_throttle,llm_routing,budget,cost_dashboard_publisher}.py` + `contexts/orchestration/{nodes/,report_pdf.py}` (FR43, FR44 PDF) + FR45 enforced by pipeline order |
| Data, Persistence, Audit (FR46-FR51) | 6/6 | `persistence/` + repos append-only + `cli/export.py` (FR50) + Hindsight bridge `cli/retain.py` (FR51) + tenant_id (FR49) |
| Operational Surface (FR52-FR56) | 5/5 | `cli/` completo (FR52, FR56 shell completion bash/zsh/fish/powershell), daemon mode con SIGTERM/SIGHUP en `paper.py`/`live.py` (FR53), web dashboard (FR54), kill-switch button (FR55) |

#### Non-Functional Requirements Coverage (51/51)

| Category | NFRs cubiertos explícitamente |
|---|---|
| Performance (NFR-P1..P8) | 8/8 — P1/P2/P5/P6 patterns, P3/P4 scheduler timings, P7 Lighthouse CI assertion <500ms LCP, P8 HeartbeatMixin |
| Security (NFR-S1..S8) | 8/8 — SOPS+age, gitleaks, whitelist, SameSite, Argon2id, slowapi rate limit, SQLCipher v2, hot-reload SIGHUP |
| Reliability (NFR-R1..R7) | 7/7 — R1 asyncio error boundaries, R2 reconciliation, R3 append-only, R5 kill-switch flag, R6 hypothesis CI-blocking, R7 backoff [3,6,12,24,48] |
| Observability (NFR-O1..O8) | 8/8 — O1 cost_meter wrapper, O2 structlog contextvars, O3 RotatingFileHandler 100MB/7d, O4 cost_dashboard_publisher 5min tick, O5 export.py CLI, ~~O6 backtest report.py removed~~, O7 prompt_hash optional, **O8 research brief citations 100% resolved or hard-fail CI** |
| Maintainability (NFR-M1..M9) | 9/9 — coverage targets, hypothesis, mypy strict, ruff/black, docs base completa, ≥10 ADRs (now 14 listed), gotchas.md added to tree, governance.md, poetry.lock + dependabot |
| Scalability (NFR-SC1..SC5) | 5/5 — tenant_id everywhere, SQLite→Postgres path, 1-container-per-tenant doc, Hindsight isolation, broker enum + JSON metadata |
| Integration (NFR-I1..I7) | 7/7 — I1 BrokerInterface ABC + contract tests, I2 IBKR backoff (=R7), I3 prompt caching, I4 perplexity_throttle.py, I5 Telegram HeartbeatMixin + queue persist, I6 WhatsApp templates checklist en runbook section, I7 MCP compatibility (Hindsight provisioned, deferred to v1.5+) |

### Implementation Readiness Validation

#### Decision Completeness

- Tech stack con versions explícitos (Python 3.11.x/3.12.x, Svelte 5.x, SvelteKit 2.x, Tailwind 4.x, etc.).
- Auth flow completo (login → JWT → contextvar → query enforcement → logout).
- Error format canónico (RFC 7807 + lista de error types en `api/errors.py`).
- SSE protocol semantics (event/id/data/retry, Pydantic typed events).
- Multi-tenant propagation (1 decisión, 6 puntos de implementación documentados).
- Backup + DR strategy (litestream + runbook scenarios).
- Heartbeat & reconnect spec con valores numéricos concretos por adapter (intervals, thresholds, backoff schedules).

#### Structure Completeness

- Tree completo file-by-file con propósito de cada archivo (~120 archivos).
- Boundaries documentados (API/Component/Data 3 niveles).
- FR-to-structure mapping completo (8 clusters).
- Critical paths data flow narrados (proposal→fill, research_brief synthesis con provenance + show-your-work).
- Liveness primitives (`shared/heartbeat.py`, `shared/backoff.py`) accesibles uniformemente.
- Resilience tests dedicated por adapter externo (4 nuevos: ibkr, telegram, hermes, perplexity).

#### Pattern Completeness

- ~25 conflict points resueltos con regla + ejemplo good + anti-pattern.
- Heartbeat & Reconnect Patterns formalizados (NEW Step 5 subsection).
- Naming conventions cubren: DB, API, JSON wire, code backend, code frontend.
- Format patterns cubren: money, dates, IDs, booleans, nulls, arrays, pagination, currency.
- Communication patterns cubren: MessageBus, frontend stores, logging.
- Process patterns cubren: errors, loading states, auth flow, validation timing.
- 13 enforcement guidelines + 6 violation detection mechanisms.

### Gap Analysis Results

**Critical Gaps:** 0
**Important Gaps:** 0 (8 previously identified — all resolved in-document)
**Nice-to-Have Gaps:** 0 (3 previously identified — all resolved in-document)

#### Resolution log (decisiones aplicadas 2026-04-28 in-doc)

| Gap inicial | Resolución |
|---|---|
| NFR-P8 IBKR heartbeat | `shared/heartbeat.py:HeartbeatMixin` añadido al tree; spec numérico 30s/90s en Step 4 "Liveness & Resilience Specifications" |
| NFR-R7/I2 IBKR backoff | `shared/backoff.py:exponential_backoff()` añadido; schedule `[3, 6, 12, 24, 48]` × 5 explicit; tras N fails → kill-switch automático |
| NFR-O3 log rotation | `RotatingFileHandler maxBytes=100MB, backupCount=7` configurado en `observability/structlog_config.py` |
| NFR-O4 cost dashboard refresh | `contexts/observability/cost_dashboard_publisher.py` + `api/sse/costs.py` con tick consolidado 5min + real-time bus events |
| NFR-I4 Perplexity rate limit | `contexts/observability/perplexity_throttle.py` token bucket + queue async + drop policy si queue > 100 |
| NFR-I5 Telegram polling resilience | `channels/telegram.py` integra HeartbeatMixin + message queue persistido SQLite re-enqueue al reconnect; `tests/integration/test_telegram_resilience.py` contract test |
| NFR-M7 gotchas.md | Añadido `docs/gotchas.md` al tree con convención append-only ≥20 entries before MVP close |
| FR44 PDF generation | `contexts/orchestration/report_pdf.py` dedicated (Plotly+Jinja+WeasyPrint) |
| ADR-005 missing | Llenado: `ADR-005-2026-04-28-heartbeat-and-reconnect-patterns.md` formaliza la decisión arquitectónica de hoy |
| NFR-P7 dashboard <500ms | Lighthouse CI step en `.github/workflows/ci.yml`; budget config en `apps/web/lighthouserc.json`; assertion fail si LCP > 500ms |
| NFR-I6 WhatsApp templates | Checklist v1.0 release item documentado en Step 4 Infrastructure & Deployment; runbook concern, no architectural |

### Architecture Completeness Checklist

**Requirements Analysis**

- [x] Project context thoroughly analyzed (56 FRs + 51 NFRs cross-mapped)
- [x] Scale and complexity assessed (1 user MVP → 1000+ v3, 6 contexts, ~5-10 strategies)
- [x] Technical constraints identified (Windows host, Python 3.11+, IBKR TWS local)
- [x] Cross-cutting concerns mapped (12 concerns enumerated en Step 2)

**Architectural Decisions**

- [x] Critical decisions documented with versions (Step 3 + Step 4)
- [x] Technology stack fully specified (backend + frontend + tooling)
- [x] Integration patterns defined (MessageBus, ports, repos, HeartbeatMixin)
- [x] Performance considerations addressed (asyncio single-loop, hot-path direct sync, NFR-P targets, Lighthouse CI)
- [x] Liveness & resilience specifications con valores numéricos por adapter

**Implementation Patterns**

- [x] Naming conventions established (DB, API, JSON wire, code backend, code frontend)
- [x] Structure patterns defined (DDD-lite con bounded contexts + cross-context rules)
- [x] Communication patterns specified (MessageBus events, store factory, logging)
- [x] Process patterns documented (errors RFC 7807, loading states, auth flow, validation timing)
- [x] Heartbeat & Reconnect patterns formalizados con HeartbeatMixin reusable

**Project Structure**

- [x] Complete directory structure defined (~120 files file-by-file)
- [x] Component boundaries established (3 niveles: API, Component, Data)
- [x] Integration points mapped (7 external + internal flow diagram)
- [x] Requirements to structure mapping complete (8 FR clusters mapeados a locations)
- [x] Resilience tests dedicated por adapter externo (4 archivos integration test)

### Architecture Readiness Assessment

**Overall Status:** READY FOR IMPLEMENTATION (0 gaps remaining)

**Confidence Level:** **HIGH** — basado en: (1) 100% FR coverage, (2) 100% NFR coverage explícito, (3) 0 gaps de cualquier severidad, (4) tech stack maduro y compatible, (5) bus factor 1 explicit consideration en estructura DDD-lite + HeartbeatMixin reusable.

**Key Strengths:**

1. **Defensive design encoded in types & contracts** (Pydantic immutable, contextvars, ABC ports) — el North Star de Step 2 se realiza en Steps 4-6.
2. **Multi-tenant ready desde día 1** sin overhead operacional (1 decisión, 6 puntos de implementación uniformemente aplicada).
3. **Observability sin construir stack propio** — Eligia citizen pattern reduce scope material y mantenimiento (NFR-M para bus factor 1).
4. **Bitemporal knowledge repository per-symbol con provenance + show-your-work** — diferenciador material; LLM no puede inventar valores porque cada claim numérico debe citar un fact con source_url + retrieved_at; cada cálculo expone formula + inputs + steps audit_trail; queryable "qué sabíamos sobre X al tiempo T". ADR-014 documenta el bitemporal schema design.
5. **Risk engine pure-function + property-tested** — invariant garantizado vía hypothesis (NFR-R6 CI-blocking).
6. **API-first decoupled frontend** — frontend reemplazable v3 si Vercel governance pivota.
7. **Liveness pattern uniforme** — HeartbeatMixin reusable + Eligia alerting external = defense-in-depth con cero infra nueva.

**Areas for Future Enhancement (post-MVP, v1.5+/v2):**

- Redis caching si benchmark muestra contención single-process (re-evaluable v2).
- Postgres migration path testing (v1.5 E2E test obligatorio NFR-SC2).
- Auto-deploy pipeline GitOps (v1.5+).
- WCAG 2.1 AA full + i18n (v3 SaaS).
- 2FA/MFA + multi-user RBAC (v3).
- TWS Gateway management automatizado (v1.5+).

### Implementation Handoff

**AI Agent Guidelines:**

1. Follow ALL architectural decisions (Steps 2-6) exactamente como documentadas.
2. Use implementation patterns Step 5 consistentemente — divergence requiere ADR justifying en `docs/adr/`.
3. Respect bounded context boundaries — NO imports profundos cross-context.
4. Refer to `docs/architecture-decisions.md` para todas las architectural questions.
5. Update `THIRD_PARTY_NOTICES.md` IF AND ONLY IF código copiado de external license-required source.
6. ISO 8601 UTC for ALL dates (wire/code/logs/docs/file-names).
7. External adapters MUST extender `HeartbeatMixin` desde `shared/heartbeat.py` y proveer test integration `test_<adapter>_resilience.py`.

**First Implementation Priority (M1 Foundation):**

```bash
# 1. Bootstrap monorepo
make bootstrap  # poetry install + pnpm install + decrypt secrets + run migrations

# 2. Skeleton backend con tenant_id enforcement
poetry new --src apps/api/iguanatrader-api
# Setup: tenant_listener, contextvars, structlog config, pydantic-settings 5-layer

# 3. Skeleton frontend
cd apps/web && pnpm create svelte@latest . --template skeleton --types typescript

# 4. shared primitives
# Implementar shared/{messagebus,heartbeat,backoff,types,contextvars,errors,time,decimal_utils,ports}.py
# Property tests primero (hypothesis sobre HeartbeatMixin idempotency, backoff schedule monotonicity)

# 5. CI básica
# .github/workflows/ci.yml: lint + type-check + test + secrets scan + lighthouse-perf step

# 6. Persistence + auth + API base + OTel exporter (orden Step 4 §Implementation Sequence)

# 7. Primer adapter externo (IBKR) implementa HeartbeatMixin como reference impl
```
