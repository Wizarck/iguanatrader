---
type: project-structure
project: iguanatrader
schema_version: 1
scope: mvp-monorepo-with-openbb-sidecar-isolation
created: 2026-04-28
updated: 2026-04-28
status: draft-pending-gate-b
sources:
  - docs/architecture-decisions.md (Step 6 Project Structure & Boundaries)
  - docs/data-model.md
  - .ai-playbook/specs/runbook-bmad-openspec.md
license: Apache-2.0 + Commons Clause (iguanatrader-proper) | AGPL-3.0 (apps/openbb-sidecar isolated)
---

# Project Structure — iguanatrader

Standalone directory map per [`.ai-playbook/specs/runbook-bmad-openspec.md`](../.ai-playbook/specs/runbook-bmad-openspec.md) §2.1 BMAD artefact requirement. This document is the authoritative file/folder layout reference; the same tree is embedded in [docs/architecture-decisions.md](architecture-decisions.md) §Project Structure for architectural context, but this file is the canonical lookup for "where does X live?".

## 1 High-level layout

```
iguanatrader/                                       # repo root (monorepo, pnpm + Poetry workspaces)
├── apps/
│   ├── api/                                        # ─── PYTHON BACKEND (Apache-2.0+CC) ───
│   ├── web/                                        # ─── SVELTEKIT FRONTEND (Apache-2.0+CC) ───
│   └── openbb-sidecar/                             # ─── AGPL-ISOLATED OpenBB Platform Docker container (FR76) ───
├── packages/
│   └── shared-types/                               # ─── AUTO-GENERATED TS TYPES from OpenAPI (Apache-2.0+CC) ───
├── config/                                         # tracked YAML configs
├── data/                                           # gitignored runtime data (SQLite, parquet, llm cache, research cache)
├── logs/                                           # gitignored structured logs
├── docs/                                           # all documentation
├── .ai-playbook/                                   # git submodule, pinned to v0.3.1+ tag
├── .secrets/                                       # gitignored, SOPS-encrypted
└── openspec/                                       # OpenSpec changes (created by /opsx:propose)
```

## 2 Repo root files

```
README.md                                       # project overview + quickstart
LICENSE                                         # Apache-2.0 + Commons Clause (iguanatrader-proper)
THIRD_PARTY_NOTICES.md                          # attribution if external code (initially empty)
SECURITY.md                                     # vuln disclosure policy
CONTRIBUTING.md                                 # for future OSS contributors (placeholder MVP)
CHANGELOG.md                                    # versioned releases
Makefile                                        # cross-package commands: bootstrap, test, lint, run-paper, run-live, dashboard, generate-types, backup-test
pnpm-workspace.yaml                             # pnpm workspace declaration (apps/web, packages/shared-types)
pyproject.toml                                  # Poetry workspace root + dev tooling shared across apps/api
poetry.lock                                     # backend deps lockfile
pnpm-lock.yaml                                  # frontend deps lockfile
.gitignore                                      # Python + Node + secrets + IDE + data/ + logs/
.gitleaksignore                                 # explicit safe-list for gitleaks
.pre-commit-config.yaml                         # gitleaks, ruff, black, mypy, eslint, prettier, openapi-typescript regen, license-boundary check
.editorconfig                                   # consistent editor settings
.dockerignore                                   # universal docker ignore at root
docker-compose.yml                              # base profile dev (default)
docker-compose.paper.yml                        # paper trading override (IBKR paper)
docker-compose.live.yml                         # live trading override (real money + --confirm-live --i-understand-the-risks per AGENTS.md §7 Override 1)
docker-compose.test.yml                         # CI test environment
AGENTS.md                                       # project dispatcher (per .ai-playbook/specs/dispatcher-chain.md)
CLAUDE.md                                       # thin router pointing to AGENTS.md
mcp-servers.project.yaml                        # project-layer MCP servers per .ai-playbook/specs/mcp-servers-schema.md
.mcp.json                                       # rendered MCP config (regenerable via scripts/mcp/render.py)
```

## 3 GitHub workflows

```
.github/
├── workflows/
│   ├── ci.yml                                  # lint + type-check + test + secrets scan + lighthouse-perf, matrix Py 3.11/3.12 + Node 20/22
│   ├── build-images.yml                        # Docker image build + push to GHCR (api, web, openbb-sidecar)
│   ├── openapi-types.yml                       # ensure regenerated TS types committed
│   └── license-boundary-check.yml              # asserts apps/api/pyproject.toml has NO OpenBB deps (FR76 enforcement)
└── dependabot.yml                              # manual review (no auto-merge)
```

## 4 Secrets layout

```
.secrets/                                       # gitignored; SOPS-encrypted at-rest (NFR-S1)
├── .sops.yaml                                  # age key recipients
├── dev.env.enc                                 # dev secrets (LLM keys, Finnhub key, FRED key, etc.)
├── paper.env.enc                               # paper IBKR creds + CAPTCHA solver API key
└── live.env.enc                                # live IBKR creds + CAPTCHA solver API key
```

## 5 Tracked configs

```
config/                                         # tracked YAML configs (validated by pydantic-settings at boot)
├── iguana.yaml                                 # master: broker, mode, paths, log level, authorized senders
├── risk.yaml                                   # protections + caps (per-trade 2%, daily 5%, weekly 15%, max 5 positions, max DD)
├── strategies.yaml                             # per-symbol strategy + params (DonchianATR, SMA Cross)
├── llm_prices.yaml                             # versioned pricing table per provider/model
├── research.yaml                               # research domain config: source enablement, scrape rate limits, brief refresh defaults
└── watchlist.yaml                              # watchlist primary/secondary tier symbols + per-symbol methodology
```

## 6 Runtime data (gitignored)

```
data/                                           # gitignored; runtime
├── iguana.db                                   # SQLite primary
├── iguana.db-wal                               # SQLite WAL
├── iguana.db-shm                               # SQLite shared memory
├── litestream/                                 # backup replicas
├── parquet_cache/                              # historical bars cache for research context (FR66)
│   └── <symbol>/<year>/<month>.parquet
├── research_cache/                             # raw payloads pointed by research_facts.raw_payload_path
│   └── <source_id>/<yyyy-mm>/<sha256>.<ext>    # append-only, integrity-checked monthly
└── llm_cache/                                  # LLM call cache TTL-based (NOT mode-aware; backtest deferred to v1.5+)
    └── <prompt_hash>.json
```

## 7 Logs (gitignored)

```
logs/                                           # gitignored; structlog rotated JSON
└── iguana.YYYY-MM-DD.log                       # daily roll via TimedRotatingFileHandler, 100MB/file, 7d retention default
```

## 8 Docs (tracked)

```
docs/                                           # all docs
├── prd.md                                      # ✅ EXISTS — sealed, capability contract (74 FRs, 51 NFRs)
├── prd-validation-report.md                    # ✅ EXISTS — PASS, 4.5/5 holistic
├── architecture-decisions.md                   # ✅ EXISTS — sealed Step 8 + Gate A amendment 2026-04-28
├── data-model.md                               # ✅ EXISTS — bitemporal research_facts + 26 entities total (Gate A amendment)
├── personas-jtbd.md                            # ✅ EXISTS — 1 persona (Arturo), 6 JTBDs, 2-role RBAC
├── project-structure.md                        # ✅ THIS DOCUMENT
├── hitl-gates-log.md                           # ✅ EXISTS — append-only Gate A/B/C/D/E/F record
├── backlog.md                                  # ✅ EXISTS — roadmap v1.0/v1.5/v2/v3
├── runbook.md                                  # extender: deployment, restart, recovery, WhatsApp templates v1.0 release checklist
├── getting-started.md                          # M1: setup local dev (incl. JSON1 SQLite prereq smoke test)
├── architecture.md                             # M1: high-level diagrams (extracto de architecture-decisions.md)
├── gotchas.md                                  # append-only dev gotchas (NFR-M7 ≥20 entries before MVP close)
├── memoria.md                                  # M7: lecciones acumuladas (LLM-generated, human-reviewed)
├── governance.md                               # v2 antes de OSS launch
├── strategies/
│   ├── donchian_atr.md                         # M1: DonchianATR strategy doc
│   ├── sma_cross.md                            # M1: SMA Cross strategy doc
│   └── methodology-profiles.md                 # M2: 5 frameworks (3-pillar, CANSLIM, Magic Formula, QARP, Multi-factor)
├── adr/                                        # Architecture Decision Records
│   ├── ADR-001-strategy-lifecycle-12-hooks.md
│   ├── ADR-002-messagebus-engines-pattern.md
│   ├── ADR-003-license-apache-commons-clause.md
│   ├── ADR-004-brokerage-model-per-broker.md
│   ├── ADR-005-2026-04-28-heartbeat-and-reconnect-patterns.md
│   ├── ADR-006-risk-engine-declarative-bypass-flow.md
│   ├── ADR-007-telegram-whatsapp-channels.md
│   ├── ADR-008-per-symbol-strategy-config.md
│   ├── ADR-009-mvp-strategies-donchian-sma.md
│   ├── ADR-010-ibkr-execution-algos-roadmap.md
│   ├── ADR-011-frontend-svelte5-sveltekit.md
│   ├── ADR-012-ddd-lite-bounded-contexts.md
│   ├── ADR-013-iso-8601-single-date-format.md
│   ├── ADR-014-2026-04-28-bitemporal-research-facts.md
│   ├── ADR-015-2026-04-28-openbb-sidecar-isolation.md
│   ├── ADR-016-2026-04-28-research-domain-and-backtest-skip.md
│   ├── ADR-017-2026-04-28-scrape-ladder-4-tiers.md
│   └── INDEX.md
└── research/                                   # research artifacts
    ├── data-sources-catalogue.md               # ✅ EXISTS — 38 sources × 12 categories
    ├── oss-algo-trading-landscape.md           # ✅ EXISTS — competitive landscape research
    ├── feature-matrix.md                       # ✅ EXISTS — comparative matrix vs OSS alternatives
    └── platforms/                              # per-platform deep dives (preserved as research artifacts; not consumed by code)
        ├── lumibot.md
        ├── nautilustrader.md
        ├── lean.md
        └── freqtrade.md
```

## 9 apps/api — Python backend (Apache-2.0+CC)

```
apps/api/
├── pyproject.toml                              # backend deps: fastapi, anthropic, ib-async, edgartools, fredapi, finnhub-python, gdelt-doc-api, structlog, etc. NO OpenBB (boundary FR76)
├── alembic.ini                                 # Alembic config
├── Dockerfile                                  # multi-stage: builder + runtime
├── .dockerignore
├── conftest.py                                 # pytest root: shared fixtures
│
├── src/iguanatrader/
│   ├── __init__.py                             # package metadata
│   ├── main.py                                 # FastAPI app factory + Kernel boot + lifespan handlers
│   ├── config.py                               # pydantic-settings 5-layer (CLI > ENV > SOPS > yaml > defaults)
│   │
│   ├── shared/                                 # ⭐ Cross-context primitives
│   │   ├── __init__.py                         # exports: TenantId, IguanaError, MessageBus, HeartbeatMixin, etc.
│   │   ├── messagebus.py                       # Pub/Sub bus + IguanaEvent base
│   │   ├── kernel.py                           # Orchestrator (boots all contexts, wires DI)
│   │   ├── types.py                            # NewType wrappers: TenantId, ProposalId, OrderId, TradeId, RequestId, FactId, BriefId
│   │   ├── contextvars.py                      # ContextVar declarations: ctx_tenant_id, ctx_request_id, ctx_correlation_id
│   │   ├── errors.py                           # IguanaError hierarchy base + subclasses comunes (incl. MissingProvenanceError, AppendOnlyViolation)
│   │   ├── time.py                             # tz utilities (UTC, US/Eastern, Europe/Madrid); ISO 8601 formatters
│   │   ├── decimal_utils.py                    # Decimal helpers for money arithmetic
│   │   ├── heartbeat.py                        # HeartbeatMixin base + OTel gauge emit (NFR-P8/R7/I2/I5)
│   │   ├── backoff.py                          # exponential_backoff() primitive (NFR-R7/I2)
│   │   └── ports.py                            # Cross-context port interfaces (TradingPort, RiskPort, ResearchPort)
│   │
│   ├── contexts/                               # ⭐ Bounded contexts (DDD-lite, 6 in MVP)
│   │   ├── __init__.py
│   │   ├── trading/                            # Strategy + Broker + Trade lifecycle
│   │   ├── risk/                               # RiskEngine + Protections
│   │   ├── approval/                           # Multi-channel approval gate
│   │   ├── observability/                      # Cost metering + OTel + structlog
│   │   ├── orchestration/                      # LangGraph routines + cron + alerts
│   │   └── research/                           # Bitemporal knowledge repo + multi-source ingestion + LLM briefs (FR57-FR79)
│   │
│   ├── persistence/                            # ⭐ DB infrastructure (cross-context)
│   │   ├── __init__.py                         # exports: get_session, Base
│   │   ├── session.py                          # SQLAlchemy session factory + engine config (JSON1 verify on boot)
│   │   ├── tenant_listener.py                  # Event listener: rejects queries without tenant_id filter
│   │   ├── append_only_listener.py             # Event listener: rejects UPDATE/DELETE on append-only tables
│   │   ├── base.py                             # Base SQLModel + naming convention
│   │   └── migrations/                         # Alembic
│   │       ├── env.py
│   │       ├── script.py.mako
│   │       └── versions/
│   │           └── <revision>_initial_schema.py
│   │
│   ├── api/                                    # ⭐ FastAPI delivery layer
│   │   ├── __init__.py
│   │   ├── app.py                              # FastAPI factory + middleware + exception handlers
│   │   ├── auth.py                             # JWT cookie middleware + dependencies
│   │   ├── deps.py                             # FastAPI Depends: get_tenant_id, get_session, etc.
│   │   ├── errors.py                           # RFC 7807 exception handlers + error type catalog
│   │   ├── dtos/                               # Pydantic API DTOs (alias_generator=to_camel)
│   │   ├── routes/                             # /api/v1/* JSON endpoints
│   │   └── sse/                                # /api/v1/sse/* event streams
│   │
│   └── cli/                                    # ⭐ typer CLI surface
│       ├── __init__.py
│       ├── main.py                             # iguana CLI app + version
│       ├── init.py                             # iguana init
│       ├── ingest.py                           # iguana ingest bars <symbol>
│       ├── research.py                         # iguana research refresh|show|list <symbol>
│       ├── paper.py                            # iguana paper (daemon)
│       ├── live.py                             # iguana live (daemon, requires --confirm-live --i-understand-the-risks per AGENTS.md §7 Override 1)
│       ├── dashboard.py                        # iguana dashboard (daemon)
│       ├── propose.py                          # iguana propose <strategy> <symbol>
│       ├── ops.py                              # iguana halt / resume / reload-config / override
│       ├── export.py                           # iguana export trades / risk-overrides
│       ├── strategies.py                       # iguana strategies list/enable/disable/set-param
│       ├── settings.py                         # iguana settings feature-flag <name> <enable|disable>
│       └── retain.py                           # iguana retain (Hindsight memory bridge)
│
└── tests/
    ├── conftest.py                             # global fixtures (mock broker, mock LLM, in-memory DB)
    ├── unit/contexts/<context>/...             # mirror context tree
    ├── integration/...                         # E2E flows
    ├── property/...                            # hypothesis tests
    └── fixtures/...                            # historical_bars, llm_replay_cache, ibkr_mock_responses
```

### 9.1 contexts/<context>/ canonical layout (DDD-lite)

```
contexts/<context>/
├── __init__.py            # Public API (re-exports). Cross-context calls SOLO via aquí
├── models.py              # Pydantic + sqlmodel domain models del context
├── ports.py               # Interfaces (BrokerInterface, ApprovalChannel, ResearchSourcePort) que el context expone
├── service.py             # Use cases / application service del context
├── repository.py          # Data access layer del context (recibe session inyectada)
├── events.py              # MessageBus event types
└── <subdomain>/           # Sub-folders cuando aplique
```

### 9.2 contexts/research/ — Research & Intelligence (FR57-FR79)

```
contexts/research/
├── __init__.py                                 # public API: ResearchService, ResearchPort
├── models.py                                   # ResearchFact, ResearchBrief, ResearchSource, SymbolUniverse, CorporateEvent, AnalystRating, WatchlistConfig
├── ports.py                                    # ResearchSourcePort, BriefSynthesizerPort
├── service.py                                  # ResearchService: ingest, refresh_brief, query_at_time
├── repository.py                               # ResearchFactRepository (bitemporal queries), BriefRepository, SourceRepository
├── events.py                                   # FactIngestedEvent, BriefRefreshedEvent, MaterialFactArrivedEvent
├── methodology/                                # 5 methodology profiles (FR58)
│   ├── __init__.py                             # MethodologyProfile ABC + registry
│   ├── three_pillar.py                         # Fundamentals + Macro + Technicals
│   ├── canslim.py                              # O'Neil CANSLIM (C-A-N-S-L-I-M dimensions)
│   ├── magic_formula.py                        # Greenblatt: ROC + Earnings Yield
│   ├── qarp.py                                 # Quality at Reasonable Price (Buffett-style)
│   └── multi_factor.py                         # Configurable weighted multi-factor
├── synthesis/                                  # LLM-driven brief generation
│   ├── __init__.py
│   ├── synthesizer.py                          # Orchestrates fact retrieval → LLM call → brief draft
│   ├── citation_resolver.py                    # Validates every numeric claim cites a fact (FR70, NFR-O8)
│   ├── audit_trail.py                          # Constructs show-your-work JSON for calculations (FR70)
│   └── prompts/                                # versioned markdown prompts per methodology
│       ├── three_pillar.md
│       ├── canslim.md
│       ├── magic_formula.md
│       ├── qarp.md
│       └── multi_factor.md
├── feature_provider/                           # Tier system for backtest-safe feature access (FR75)
│   ├── __init__.py                             # @feature_provider decorator with tier marker
│   ├── tier_a.py                               # Native PiT: EDGAR XBRL, ALFRED
│   ├── tier_b.py                               # Snapshot collected: yfinance via OpenBB sidecar, Finnhub current, Polygon free
│   └── tier_c.py                               # One-shot bootstrap: Stooq, MSCI tool
├── sources/                                    # Per-source adapters (FR59-FR67)
│   ├── __init__.py                             # SourceRegistry; registers all by source_id
│   ├── sec_edgar.py                            # SEC EDGAR via edgartools (FR59 — 10-K/10-Q/8-K/Form4/13F)
│   ├── fred.py                                 # FRED + ALFRED via fredapi (FR60)
│   ├── bls.py                                  # BLS API (FR60)
│   ├── bea.py                                  # BEA API (FR60)
│   ├── finnhub.py                              # Finnhub free tier: news + sentiment + calendars + ratings (FR61, FR62, FR64)
│   ├── gdelt.py                                # GDELT DOC 2.0 + BigQuery PESTEL (FR61, FR67)
│   ├── openfda.py                              # FDA approvals catalysts (FR62)
│   ├── openinsider.py                          # OpenInsider scraping (FR63 aggregated)
│   ├── openbb_sidecar.py                       # HTTP client to apps/openbb-sidecar (FR76)
│   ├── yfinance_proxy.py                       # yfinance via OpenBB sidecar — fundamentals + ratings + ESG (FR64, FR65)
│   ├── finviz_scrape.py                        # Finviz HTML scrape (Tier 2 ladder)
│   ├── wgi_world_bank.py                       # WGI governance indicators (FR67)
│   ├── vdem.py                                 # V-Dem academic dataset CSV (FR67)
│   ├── ibkr_bars.py                            # IBKR historical bars adapter (FR66 primary)
│   ├── yahoo_bars_fallback.py                  # Yahoo Finance bars fallback (FR66 secondary)
│   ├── hindsight_recall.py                     # Hindsight recall (FR81 gated read; NFR-I8 graceful)
│   └── hindsight_retain.py                     # Hindsight retain (FR80 always-on write)
├── scraping/                                   # 4-tier scraping ladder (FR77, FR79)
│   ├── __init__.py                             # ScrapeLadder abstraction
│   ├── tier1_webfetch.py                       # httpx + BS4
│   ├── tier2_playwright.py                     # Chromium headless
│   ├── tier3_camoufox.py                       # Camoufox MCP stealth Firefox
│   ├── tier4_captcha.py                        # Camoufox + paid captcha solver
│   ├── robots_check.py                         # urllib.robotparser programmatic
│   └── user_agent.py                           # iguanatrader/<version> identifying UA (FR79)
└── scheduler.py                                # APScheduler config for fact ingestion + brief refresh schedules (FR72)
```

### 9.3 api/routes/ — REST endpoints

```
api/routes/
├── __init__.py
├── auth.py                                     # /api/v1/auth/* (login, logout, refresh)
├── trades.py                                   # /api/v1/trades
├── approvals.py                                # /api/v1/approvals
├── risk.py                                     # /api/v1/risk + risk-overrides
├── strategies.py                               # /api/v1/strategies + per-symbol config
├── portfolio.py                                # /api/v1/portfolio
├── costs.py                                    # /api/v1/costs
├── research.py                                 # /api/v1/research/* (briefs, facts, watchlist, sources)
├── settings.py                                 # /api/v1/settings/feature-flags (admin role; FR81 toggle)
└── ops.py                                      # /api/v1/halt, /resume, /reload-config, /override
```

### 9.4 api/sse/ — Server-Sent Events streams

```
api/sse/
├── __init__.py
├── equity.py                                   # /sse/equity (fill events)
├── approvals.py                                # /sse/approvals (queue updates)
├── risk.py                                     # /sse/risk (cap state changes)
├── costs.py                                    # /sse/costs (real-time + 5min tick, NFR-O4)
├── research.py                                 # /sse/research (BriefRefreshedEvent, MaterialFactArrivedEvent push)
└── alerts.py                                   # /sse/alerts (Tier 1+2)
```

### 9.5 tests/ — Backend test layout

```
tests/
├── conftest.py
├── unit/
│   └── contexts/
│       ├── trading/test_strategies.py
│       ├── trading/test_brokers.py
│       ├── risk/test_engine.py
│       ├── risk/test_protections.py
│       ├── approval/test_service.py
│       ├── approval/test_channels.py
│       ├── observability/test_cost_meter.py
│       ├── orchestration/test_scheduler.py
│       ├── research/test_bitemporal_queries.py    # FR68 ADR-014
│       ├── research/test_provenance_enforcement.py # FR69 missing source_id raises
│       ├── research/test_audit_trail_render.py    # FR70 show-your-work JSON valid
│       ├── research/test_methodology_profiles.py  # FR58 all 5 frameworks
│       ├── research/test_feature_provider_tier.py # FR75 A/B/C tier markers + None handling
│       ├── research/test_citation_resolver.py     # NFR-O8 broken citations fail render
│       └── research/test_scrape_ladder.py         # FR77 4-tier escalation
├── integration/
│   ├── test_proposal_to_fill_flow.py           # E2E: signal → research_brief → risk → approval → submit → fill
│   ├── test_risk_override_flow.py              # E2E: rejected → override → audit
│   ├── test_kill_switch_flow.py                # E2E: trigger via 4 sources
│   ├── test_reconciliation.py                  # broker↔cache reconcile post-disconnect
│   ├── test_research_brief_refresh.py          # E2E: ingest facts (EDGAR+FRED+news) → synthesize → render with citations
│   ├── test_openbb_sidecar_health.py           # HTTP loopback healthcheck + heartbeat
│   ├── test_cross_tenant_isolation.py          # tenant_id enforcement
│   ├── test_ibkr_resilience.py                 # disconnect→backoff→kill-switch (NFR-R7/I2/P8)
│   ├── test_telegram_resilience.py             # long-polling reconnect + queue persist (NFR-I5)
│   ├── test_hermes_resilience.py               # Hermes/WhatsApp adapter heartbeat
│   ├── test_perplexity_throttle.py             # rate limit + queue + drop policy (NFR-I4)
│   ├── test_trades_state_audit_consistency.py  # data-model.md §7.4 — state cache vs audit log fold
│   └── test_sqlite_to_postgres_migration.py    # NFR-SC2 v1.5 milestone
├── property/
│   ├── test_risk_caps_invariant.py             # hypothesis: never breach
│   ├── test_decimal_arithmetic.py              # money arithmetic invariants
│   ├── test_strategy_no_lookahead.py           # on_bar(t) cannot access t+1
│   └── test_message_ordering.py                # MessageBus event ordering
└── fixtures/
    ├── historical_bars/                        # parquet fixtures
    ├── llm_replay_cache/                       # cached LLM responses
    ├── research_facts_corpus/                  # bitemporal fixtures (EDGAR snippets, FRED series)
    └── ibkr_mock_responses/                    # mock broker responses
```

## 10 apps/web — SvelteKit frontend (Apache-2.0+CC)

```
apps/web/
├── package.json
├── pnpm-lock.yaml
├── svelte.config.js
├── vite.config.ts
├── tsconfig.json
├── tailwind.config.ts
├── postcss.config.cjs
├── playwright.config.ts
├── lighthouserc.json                           # NFR-P7 budget config
├── eslint.config.js
├── prettier.config.js
├── Dockerfile                                  # Node builder + Nginx serve assets
├── .dockerignore
│
├── src/
│   ├── app.html                                # SvelteKit shell
│   ├── app.css                                 # Tailwind base + globals
│   ├── app.d.ts                                # global types
│   ├── hooks.server.ts                         # auth middleware, tenant context
│   ├── hooks.client.ts                         # global error → OTel
│   │
│   ├── routes/                                 # file-based routing
│   │   ├── +layout.svelte
│   │   ├── +layout.ts                          # root load (auth check)
│   │   ├── +page.svelte                        # / (equity curve + drawdown + positions + kill-switch)
│   │   ├── +error.svelte
│   │   ├── (auth)/
│   │   │   └── login/
│   │   │       ├── +page.svelte
│   │   │       └── +page.server.ts             # form action: POST /api/v1/auth/login
│   │   └── (app)/
│   │       ├── +layout.svelte                  # authenticated layout
│   │       ├── +layout.server.ts               # tenant resolution
│   │       ├── approvals/
│   │       ├── trades/
│   │       ├── portfolio/
│   │       ├── costs/
│   │       ├── risk/
│   │       ├── research/
│   │       │   ├── +page.svelte                # watchlist + per-symbol research_brief overview
│   │       │   ├── +page.server.ts
│   │       │   └── [symbol]/
│   │       │       ├── +page.svelte            # symbol detail: brief vigente + facts timeline + citations
│   │       │       ├── +page.server.ts
│   │       │       └── audit-trail/[brief_version]/
│   │       │           ├── +page.svelte        # show-your-work view per calculation
│   │       │           └── +page.server.ts
│   │       └── settings/
│   │           ├── +page.svelte                # tenant settings: feature flags toggles (Hindsight recall + future)
│   │           └── +page.server.ts             # admin-role gated; PATCH /api/v1/settings/feature-flags
│   │
│   ├── lib/
│   │   ├── api/
│   │   │   ├── client.ts                       # fetch wrapper + interceptors (401 redirect, error parsing)
│   │   │   ├── auth.ts
│   │   │   ├── trades.ts
│   │   │   ├── approvals.ts
│   │   │   ├── risk.ts
│   │   │   ├── strategies.ts
│   │   │   ├── portfolio.ts
│   │   │   ├── costs.ts
│   │   │   ├── research.ts                     # GET briefs / facts / watchlist / sources
│   │   │   └── ops.ts
│   │   ├── components/
│   │   │   ├── EquityCurve.svelte              # TradingView Lightweight Charts wrapper
│   │   │   ├── DrawdownGauge.svelte
│   │   │   ├── PositionsTable.svelte
│   │   │   ├── ApprovalCard.svelte
│   │   │   ├── ApprovalList.svelte
│   │   │   ├── TradesTable.svelte
│   │   │   ├── CostBreakdownChart.svelte       # ApexCharts USD/día per provider
│   │   │   ├── RiskCapsBar.svelte
│   │   │   ├── KillSwitchButton.svelte
│   │   │   ├── OverrideForm.svelte             # reason ≥20 chars + double confirm
│   │   │   ├── StockRow.svelte
│   │   │   ├── ConnectionIndicator.svelte
│   │   │   ├── SkeletonLoader.svelte
│   │   │   ├── Toast.svelte
│   │   │   ├── nav/Sidebar.svelte
│   │   │   ├── research/BriefHeader.svelte     # symbol + version + methodology + score badge
│   │   │   ├── research/FactTimeline.svelte    # bitemporal facts timeline visualization
│   │   │   ├── research/CitationLink.svelte    # inline [fact_id] → tooltip with source URL + retrieved_at
│   │   │   ├── research/AuditTrailViewer.svelte # show-your-work per calculation
│   │   │   └── research/MethodologyBadge.svelte
│   │   ├── stores/
│   │   │   ├── tenantStore.ts
│   │   │   ├── authStore.ts
│   │   │   ├── equityStore.ts                  # SSE-fed equity ticks
│   │   │   ├── approvalsStore.ts
│   │   │   ├── riskStore.ts
│   │   │   ├── alertsStore.ts
│   │   │   ├── connectionStore.ts
│   │   │   ├── researchStore.ts                # SSE-fed brief refresh + material fact arrived
│   │   │   └── themeStore.ts
│   │   ├── composables/
│   │   │   ├── useEventSource.ts
│   │   │   ├── useCountdown.ts
│   │   │   ├── useFormatPrice.ts
│   │   │   └── useCostStream.ts                # /sse/costs consumer
│   │   ├── utils/
│   │   │   ├── format.ts
│   │   │   ├── decimal.ts
│   │   │   └── tz.ts
│   │   ├── types/
│   │   │   └── index.ts                        # re-exports from packages/shared-types
│   │   ├── i18n/
│   │   │   ├── en.json                         # placeholder MVP, populate v3
│   │   │   └── es.json
│   │   └── icons/
│   │
│   └── service-worker.ts                       # PWA-ready, disabled MVP
│
├── static/
│   ├── favicon.svg
│   ├── robots.txt
│   └── manifest.webmanifest                    # PWA manifest, activated v2
│
└── tests/
    ├── e2e/
    │   ├── auth.spec.ts                        # login flow
    │   ├── approval-flow.spec.ts               # propose → approve → fill (Journey 1)
    │   ├── override-flow.spec.ts               # cap rejected → override → audit (Journey 2)
    │   ├── weekly-review.spec.ts               # PDF generation (Journey 3)
    │   ├── failure-recovery.spec.ts            # disconnect + reconcile (Journey 4)
    │   └── research-brief-view.spec.ts         # symbol detail with citations + audit trail
    └── fixtures/
```

## 11 apps/openbb-sidecar — AGPL-isolated OpenBB Platform (FR76)

```
apps/openbb-sidecar/
├── pyproject.toml                              # AGPL deps: openbb-platform, openbb-* extensions. INDEPENDENT from apps/api/pyproject.toml
├── poetry.lock
├── Dockerfile                                  # standalone container with own Python env
├── .dockerignore
├── README.md                                   # AGPL-3.0 attribution + boundary explanation
├── LICENSE                                     # AGPL-3.0 license text (separate from iguanatrader-proper Apache+CC)
│
└── src/openbb_sidecar/
    ├── __init__.py
    ├── main.py                                 # FastAPI app on localhost:8765
    ├── config.py
    ├── routes/
    │   ├── __init__.py
    │   ├── health.py                           # GET /health (HeartbeatMixin target)
    │   ├── equity.py                           # GET /v1/equity/fundamentals/{symbol}, /v1/equity/ratings/{symbol}, /v1/equity/esg/{symbol}
    │   └── economy.py                          # GET /v1/economy/macro/{indicator}
    └── adapters/
        └── openbb_facade.py                    # thin wrapper over OpenBB SDK
```

**License-boundary enforcement** (FR76, ADR-015):
- Pre-commit hook + CI workflow `license-boundary-check.yml` greps `apps/api/pyproject.toml` for OpenBB packages → fails if found.
- Cross-import from `apps/api/src/iguanatrader/` to `apps/openbb-sidecar/src/openbb_sidecar/` PROHIBITED — pytest collection rule asserts no offending imports.
- Containers communicate exclusively via HTTP loopback `localhost:8765`.

## 12 packages/shared-types — Auto-generated TS types (Apache-2.0+CC)

```
packages/shared-types/
├── package.json
├── tsconfig.json
├── src/
│   ├── index.ts                                # re-exports
│   └── generated.ts                            # ⚠️ AUTO-GENERATED via openapi-typescript; do NOT edit manually
└── README.md                                   # how to regenerate (pnpm run generate-types)
```

## 13 .ai-playbook (git submodule)

```
.ai-playbook/                                   # git submodule, pinned to semver tag (currently v0.3.1+)
├── specs/                                      # universal norms (verdict-contract, agent-contract, runbook-bmad-openspec, etc.)
├── runbooks/                                   # operational runbooks (hindsight-retain, onboard-new-project, etc.)
├── scripts/                                    # validation + drift checks + render scripts invoked by pre-commit/CI
├── templates/                                  # OpenSpec templates
├── rfcs/                                       # RFCs (e.g. RFC-0001 skills migration)
└── consumers.yaml                              # registry of consumer projects
```

## 14 openspec/ (created by /opsx:propose)

```
openspec/
├── specs/                                      # archived spec capabilities (promoted via /opsx:archive)
└── changes/
    └── <change-id>/                            # one folder per active change (created by /opsx:propose)
        ├── proposal.md
        ├── design.md
        ├── specs/<capability>/spec.md
        └── tasks.md
```

## 15 Boundary summary

| Boundary | Tooling | Enforcement |
|---|---|---|
| `tenant_id` everywhere | SQLAlchemy event listener | Runtime rejection + CI integration test |
| Append-only tables | SQLAlchemy event listener | Runtime rejection + CI integration test |
| Cross-context imports | Custom ruff rule + pytest collection | Pre-commit + CI |
| `apps/api/` ↔ `apps/openbb-sidecar/` AGPL boundary | License-boundary check workflow + cross-import test | Pre-commit + CI (hard-block) |
| Frontend ↔ Backend types | openapi-typescript pipeline + pre-commit regen | Pre-commit + CI diff = 0 |
| Provenance per research_fact | DB CHECK constraints + CI integration test | Runtime rejection (insert) + CI |
| Citation resolution | CI integration test | CI hard-fail; live soft-fail with WARNING |

## 16 Cross-references

- [docs/architecture-decisions.md](architecture-decisions.md) §Project Structure — same tree embedded for architectural context.
- [docs/data-model.md](data-model.md) — entity definitions referenced by `apps/api/src/iguanatrader/contexts/<context>/models.py`.
- [docs/personas-jtbd.md](personas-jtbd.md) — persona + RBAC role mapping referenced by `users.role` schema.
- [docs/hitl-gates-log.md](hitl-gates-log.md) — Gate A amendment 2026-04-28 cascade documented.
- [.ai-playbook/specs/runbook-bmad-openspec.md](../.ai-playbook/specs/runbook-bmad-openspec.md) §2.1 — artefact requirement.
