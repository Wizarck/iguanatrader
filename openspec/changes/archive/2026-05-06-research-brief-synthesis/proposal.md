## Why

R1 (`research-bitemporal-schema`, archived 2026-05-06) shipped the bitemporal `research_facts` + versioned `research_briefs` schema + 4 route stubs returning 501; R2/R3/R4 (Wave-3 siblings) are landing source adapters in parallel. None of that is end-user-visible: the dashboard's `/research/[symbol]` route still renders "loading…" and every brief endpoint replies 501. **R5 is the slice that turns the research domain into product** — the synthesis layer that takes facts from R1-R4, runs them through 5 methodologies (3-pillar, CANSLIM, Magic Formula, QARP, Multi-factor — FR58), invokes the LLM with provenance-preserving prompts, persists immutable versioned briefs (FR71-FR73), and renders the `/research/[symbol]` + `/audit-trail/[brief_version]` surfaces locked in [docs/ux/j3.md](../../../docs/ux/j3.md) §3 Steps 2-3. Every numeric claim in every brief is one click from its source fact (NFR-O8 citation chain — render fails if any citation is broken). The audit trail makes "show your work" a hard contract: every computed metric persists formula + inputs + intermediate steps + final output to `research_audit_trail` so JTBD-4 (anti-hallucination) becomes structurally impossible to violate. Now is the right time because R1 is archived (the foundational schema is stable), R2/R3/R4 are in flight on disjoint write paths and can be mocked via `SourcePort` fakes during R5 dev, O1 (`observability-cost-meter`) is archived and provides the `cost_meter` + `replay_cache` that R5's LLM client consumes, and W1 (`dashboard-svelte-skeleton`) shipped the `/research/[symbol]/+page.svelte` "loading…" stub with the dynamic-Sidebar contract — R5 swaps the body without touching the sidebar.

## What Changes

- **5 methodology frameworks** — `apps/api/src/iguanatrader/contexts/research/methodology/{three_pillar,canslim,magic_formula,qarp,multi_factor}.py` each ship a pure function `score(features: dict[str, Decimal | None]) -> MethodologyResult` returning ranking + per-pillar score + rationale text. Pure-functional, deterministic, no LLM calls (LLM consumes the result for prose narration in `synthesizer.py`). Per FR58, all 5 frameworks shipped MVP day 1.
- **Tier-aware feature provider** — `contexts/research/feature_provider/{tier_a,tier_b,tier_c}.py`. Tier-A (native PiT: EDGAR XBRL `effective_from`, FRED ALFRED vintage, IBKR historical bars with timestamp) — full historical access. Tier-B (snapshot-collected with `retrieved_at` constraint: Finnhub news, GDELT events) — available since collection-start date. Tier-C (one-shot bootstrap: WGI, V-Dem) — only at the bootstrapped timestamp. **CI-blocking assertion** (`tests/unit/contexts/research/test_feature_provider_tier.py`) greps query patterns and refuses Tier-B usage in backtest features (FR75 spirit).
- **LLM synthesizer** — `contexts/research/synthesis/synthesizer.py` orchestrates: `feature_provider.fetch(symbol, methodology)` → `methodology.score(features)` → fill prompt template at `synthesis/prompts/<methodology>.md` → invoke LLM via O1's `ObservabilityClient` (cost_meter + replay_cache + budget gate) → parse brief markdown + extract `[fact:<uuid>]` markers → persist `research_briefs` row + `research_audit_trail` rows for every computed metric. Citation marker syntax locked: `[fact:<uuid>]` (NOT integer ids — UUID prevents cross-brief collisions; verbatim from j3.md §9 resolved 2026-05-05).
- **citation_resolver** — `contexts/research/synthesis/citation_resolver.py` parses brief body for `[fact:<uuid>]` markers, resolves each to its `research_facts` row, returns `(rendered_html, citation_bundle)` for the API/SSE consumer. Broken marker → renders as `Badge variant="warn"` per [components.md §4.3](../../../docs/ux/components.md#43-citationlinksvelte) "broken state". CI integration test asserts every claim in a synthesised brief resolves.
- **audit_trail** — `contexts/research/synthesis/audit_trail.py` + new `research_audit_trail` table (migration `0008_research_audit.py`) persists every LLM call (input prompt + output + token count + USD cost + duration_ms + model_id) per brief_version. Replayable for compliance via O1's deterministic `replay_cache`. Append-only at L1 + L2.
- **Service + scheduler** — `contexts/research/service.py` (`BriefService.refresh(symbol, methodology)` orchestrates synthesis with retry-on-version-collision per R1 D5; rate-limit gate via slowapi 5/min per j3.md §3 Step 2) + `contexts/research/scheduler.py` (ingestion + refresh scheduling hooks consumed by O2 routines).
- **API routes (full impl, replaces R1 stubs)** — `api/routes/research.py` swaps stub bodies in-place (signatures unchanged per R1 D6): `GET /research/briefs/{symbol}` (latest brief w/ resolved citations) + `GET /research/briefs/{brief_id}/audit-trail` (full audit) + `GET /research/facts/{symbol}` (FactTimeline payload) + `POST /research/briefs/{symbol}/refresh` (forces re-synthesis; rate-limited 5/min). `api/sse/research.py` emits `research.brief.refresh.progress`, `research.brief.refreshed`, `research.fact.recorded`.
- **CLI** — `cli/research.py` (typer) ships `iguanatrader research refresh-brief <symbol>` + `iguanatrader research audit <brief_id>` (renders audit_trail entries to stdout in markdown).
- **Frontend** — `apps/web/src/routes/(app)/research/[symbol]/+page.{svelte,server.ts}` (full impl, replaces W1 "loading…" stub) + `+page.svelte` for `[symbol]/audit-trail/[brief_version]` nested route. Both consume the 5 components per components.md §4.
- **5 components (locked design tokens)** — `apps/web/src/lib/components/research/{BriefHeader,FactTimeline,CitationLink,AuditTrailViewer,MethodologyBadge}.svelte` per [docs/ux/components.md §4.1-§4.5](../../../docs/ux/components.md#4-research-domain-components-journey-3) verbatim contracts (props + states + tokens + storybook stories). Tier badges + per-methodology colour map use the locked OKLCH tokens from DESIGN.md §1.
- **Tests** — 1 integration test (`test_research_brief_refresh.py` E2E refresh-brief-and-render flow) + 4 unit tests (`test_audit_trail_render`, `test_methodology_profiles`, `test_feature_provider_tier`, `test_citation_resolver`) + Playwright e2e for `/research/[symbol]` + audit-trail navigation + Lighthouse a11y ≥ 95 on both research pages.
- **Out of scope**: Hindsight integration (R6 — feature_flag toggle in Settings + recall step in synthesizer; R5 ships the Hindsight-OFF synthesis path only); trading routes & T4 frontend pages; orchestration scheduler routines (O2 — `BriefService.refresh()` is callable but not yet cron-scheduled; O2 wires the cron); SSE concrete subscribers (O2 + W1 stores already declare consumers; R5 mounts the publishers); per-tenant LLM model selection UI (defer to v1.5); multi-symbol batch brief refresh.

## Capabilities

### New Capabilities

(none — R5 extends the existing `research` capability planted by R1.)

### Modified Capabilities

- `research`: replaces R1's stub-501 route contract with full synthesis. Adds 5 methodology requirements (FR58), tier-aware feature provider with CI assertion (FR75), citation_resolver guarantee (FR71 + NFR-O8), audit_trail persistence (FR70), versioned brief refresh contract (FR72-FR73), perf budget for refresh (NFR-P9 < 30s p95). The existing R1 requirements (bitemporal schema, provenance, hybrid payload, append-only L1+L2, per-symbol monotonic version, cross-tenant `research_sources`) carry forward unchanged — R5 only ADDs requirements that build on top.

## Impact

- **Affected code (R5-owned, write-allowed)**:
  - `apps/api/src/iguanatrader/contexts/research/methodology/{__init__,three_pillar,canslim,magic_formula,qarp,multi_factor}.py` (NEW × 6).
  - `apps/api/src/iguanatrader/contexts/research/feature_provider/{__init__,tier_a,tier_b,tier_c,base}.py` (NEW × 5).
  - `apps/api/src/iguanatrader/contexts/research/synthesis/{__init__,synthesizer,citation_resolver,audit_trail,prompts/__init__.py,prompts/three_pillar.md,prompts/canslim.md,prompts/magic_formula.md,prompts/qarp.md,prompts/multi_factor.md}` (NEW × 10).
  - `apps/api/src/iguanatrader/contexts/research/{service,scheduler}.py` (NEW × 2).
  - `apps/api/src/iguanatrader/contexts/research/repository.py` (MOD) — implement the `insert_brief(...)` method that R1 left as a `ResearchStubNotImplementedError` raise; signature unchanged. Add `insert_audit_trail_entry(...)` for the new `research_audit_trail` table.
  - `apps/api/src/iguanatrader/contexts/research/models.py` (MOD) — add `ResearchAuditTrail` ORM model matching the new migration table.
  - `apps/api/src/iguanatrader/migrations/versions/0008_research_audit.py` (NEW) — `research_audit_trail` table + L2 trigger (append-only) + indexes; `down_revision = "0007"`.
  - `apps/api/src/iguanatrader/api/routes/research.py` (MOD) — replace the four stub bodies with full impl (signatures + DTOs unchanged from R1).
  - `apps/api/src/iguanatrader/api/sse/research.py` (NEW) — 3 SSE event publishers.
  - `apps/api/src/iguanatrader/api/dtos/research.py` (MOD) — extend `BriefResponse` with `audit_trail_summary`, add `BriefRefreshProgressEvent` for SSE; existing fields kept verbatim.
  - `apps/api/src/iguanatrader/cli/research.py` (NEW) — typer subcommands.
  - `apps/web/src/routes/(app)/research/[symbol]/{+page.svelte,+page.server.ts}` (NEW) — replaces W1 stub.
  - `apps/web/src/routes/(app)/research/[symbol]/audit-trail/[brief_version]/{+page.svelte,+page.server.ts}` (NEW × 2).
  - `apps/web/src/lib/components/research/{BriefHeader,FactTimeline,CitationLink,AuditTrailViewer,MethodologyBadge}.svelte` (NEW × 5).
  - `apps/web/src/lib/research/{render-brief,resolve-citations}.ts` (NEW × 2) — citation marker parser.
  - `apps/api/tests/integration/test_research_brief_refresh.py` (NEW) + `apps/api/tests/unit/contexts/research/{test_audit_trail_render,test_methodology_profiles,test_feature_provider_tier,test_citation_resolver}.py` (NEW × 4).
  - `apps/web/tests-e2e/research-brief-detail.spec.ts` + `research-audit-trail.spec.ts` (NEW × 2).
  - `docs/gotchas.md` (MOD) — gotchas #50+ (LLM cost-runaway guard, citation marker UUID collision, audit replay non-determinism).
- **Affected code (R1/O1/W1-owned, read-only consumed)**:
  - `iguanatrader.contexts.research.{models,ports,repository,events,errors}` from R1 — full surface consumed unchanged.
  - `iguanatrader.contexts.observability.cost_meter` + `.replay_cache` + `.budget` + `.llm_routing` from O1 — `synthesizer.py` constructs an `ObservabilityClient` and routes every LLM call through it (per-call USD ledger + monthly budget gate + deterministic replay for tests).
  - `iguanatrader.shared.messagebus.MessageBus` from slice 2 — `synthesizer.py` emits `ResearchBriefSynthesized` after successful insert (R1 declared the event class).
  - `apps/web/src/lib/composables/{useFetch,useSSE}.ts` from W1 — research pages consume `useFetch` for `/api/v1/research/*` and `useSSE` for `/api/v1/stream/research`.
  - `apps/web/src/lib/components/{Card,Badge,Button,Input,Spinner,SkeletonLoader,Toast,EmptyState}.svelte` from W1 — composed by the 5 R5 components per components.md §4.
- **Affected APIs**: `/api/v1/research/briefs/{symbol}` + `/research/briefs/{brief_id}/audit-trail` + `/research/facts/{symbol}` + `/research/briefs/{symbol}/refresh` flip from 501 to 200. New SSE endpoint `/api/v1/stream/research`. OpenAPI `/openapi.json` schema for `BriefResponse`/`AuditTrailEntry` extended (additive — typegen regenerates `packages/shared-types/src/index.ts` automatically).
- **Affected dependencies**: no new Python deps (all primitives — LangChain LLM client, structlog, Pydantic v2, SQLAlchemy — already in slice 1's `pyproject.toml`; `langgraph` was added by O1). No new frontend deps (lucide-svelte icons + Tailwind tokens already shipped by W1).
- **Prerequisites**:
  - **R1 `research-bitemporal-schema`** (archived 2026-05-06) — mandatory; provides the schema + ports + DTO + route stubs R5 swaps.
  - **O1 `observability-cost-meter`** (archived 2026-05-06) — mandatory; `synthesizer.py` consumes `cost_meter` + `replay_cache` + `budget` + `llm_routing`.
  - **W1 `dashboard-svelte-skeleton`** (archived 2026-05-06) — mandatory; `/research/[symbol]/+page.svelte` stub + Sidebar dynamic enumeration + `useFetch`/`useSSE` composables + design tokens.
  - **R2/R3/R4 source adapters** (Wave-3 siblings, may NOT be merged at R5 dev start) — **mocked via `SourcePort` fakes** in `tests/fakes/source_port_fakes.py`. R5 dev does NOT block on R2/R3/R4 merge order; production deployment of R5 + R2/R3/R4 happens in any order (dynamic discovery + adapter registry).
- **Capability coverage** (per [docs/openspec-slice.md](../../../docs/openspec-slice.md) row R5):
  - **FR58** (5 methodologies — 3-pillar, CANSLIM, Magic Formula, QARP, Multi-factor): `methodology/*` 5 pure-function files.
  - **FR71** (LLM-synthesised brief with citations + audit_trail): `synthesizer.py` + `citation_resolver.py` + `audit_trail.py`.
  - **FR72** (refresh on schedule + on-trigger): `service.py::BriefService.refresh()` callable from cron (O2) or POST endpoint or fact-ingest event subscriber.
  - **FR73** (immutable per-version): R1 D5 contract preserved (per-`(tenant, symbol)` monotonic version + retry-on-collision).
  - **FR74** (proposal-to-brief linkage): R5 ensures `BriefResponse.id` is stable; T4 reads it from `trade_proposals.research_brief_id` FK.
  - **FR75** (tier-based feature availability): `feature_provider/{tier_a,tier_b,tier_c}.py` + CI-blocking `test_feature_provider_tier.py` greps query patterns.
  - **NFR-P9** (refresh < 30s p95): pytest-benchmark gate in CI; cache hit ratio ≥ 40% achieved via O1's `replay_cache` + per-symbol fact prefetch.
  - **NFR-O8** (citation chain provenance — render fails on broken citations): `citation_resolver.py` returns broken-citation as `Badge variant="warn"` AND emits structlog `research.citation.broken` event; CI integration test fails on any broken-citation in test corpus.
- **Out of scope** (per [docs/openspec-slice.md](../../../docs/openspec-slice.md) row R5 + design discipline):
  - Hindsight `recall` step in synthesizer (R6 — wires the feature_flag-gated step; R5 ships the no-recall baseline only).
  - O2 cron scheduling of brief refresh (R5 ships `BriefService.refresh()`; O2 wires the cron + premarket/midday/postmarket nodes).
  - T4 trading routes (`trade_proposals.research_brief_id` FK consumed but not populated by R5).
  - `/alerts` route + drawer pattern (W1 + O2).
  - PDF weekly review (O2; consumes audit_trail JSON via the same API R5 ships).
  - As-of replay UI (`/research/[symbol]?as_of=<ts>`) — j3.md §3 Step 4 — **DEFERRED to v1.5**: R5 ships the bitemporal `as_of(symbol, at)` repository call (R1 ships it already) but NOT the comparison-view UI; route accepts the param but renders the latest brief with a TBD banner.
  - Pattern observation archive (`/research/insights`) — R6 owns.
  - Per-tenant LLM model override UI in /settings.

## Acceptance

- All 5 methodologies callable via `BriefService.refresh(symbol, methodology="canslim")` etc.; each produces a deterministic ranking + score + rationale for a fixed feature input (snapshot-tested).
- Citation chain reproducible end-to-end: given a brief and the original facts, regenerating yields the same citation bundle (deterministic via O1 `replay_cache`); brief PROSE is LLM-stochastic but citations are NOT (caveat documented in design D9).
- `audit_trail` persists for every computed metric — integration test asserts every numeric in a synthesised brief either (a) is a direct fact citation OR (b) has a `research_audit_trail` row with formula + inputs + final_output.
- `feature_provider` tier-A/B/C enforced via CI: `test_feature_provider_tier.py` greps backtest query patterns (`pytest -k backtest`) and FAILS the CI run if any Tier-B feature query lacks an explicit `since` constraint.
- `/research/[symbol]` renders in <500ms localhost (W1 NFR-P7 baseline); brief refresh completes <30s p95 (NFR-P9); Lighthouse a11y ≥ 95 on `/research/[symbol]` and `/research/[symbol]/audit-trail/[brief_version]`.
- All four `/api/v1/research/*` routes return 200 + RFC 7807 on errors (no more 501 from R1 stubs); SSE `/api/v1/stream/research` emits `research.brief.refresh.progress` events during synthesis.
