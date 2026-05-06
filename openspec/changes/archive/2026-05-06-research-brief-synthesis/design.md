## Context

R5 is the **synthesis layer** — the first slice that turns research-domain primitives (facts + ports + repository from R1; source adapters from R2/R3/R4; cost meter + replay cache from O1; dashboard skeleton + design tokens from W1) into product surface that an end user can read and trust. It is the **biggest Wave-3 slice** because it spans backend (5 methodologies + LLM synthesizer + citation resolver + audit trail + tier-aware feature provider + service + scheduler + 4 routes + SSE + CLI) and frontend (5 components + 2 nested routes + brief markdown renderer + e2e tests) and ships the first real LLM consumer through O1's cost/replay infrastructure.

State at R5 start (assumed; halt-on-violation in task 1.1):

- **R1 archived** (`openspec/changes/archive/2026-05-06-research-bitemporal-schema/`) — `research_facts`, `research_briefs`, `corporate_events`, `analyst_ratings`, `research_sources`, `symbol_universe`, `watchlist_configs` schemas + `SourcePort` Protocol + `ResearchRepository` with `as_of/insert_fact/supersede_fact/latest_brief` (and a `ResearchStubNotImplementedError`-raising `insert_brief` stub R5 fills) + 4 route stubs + DTO shapes (`BriefResponse`, `FactResponse`, `CitationDetail`, `AuditTrailEntry`).
- **O1 archived** — `cost_meter` (per-call USD ledger), `replay_cache` (deterministic LLM replay for tests), `budget` (per-tenant monthly cap), `llm_routing` (Claude/Sonnet/Haiku/GPT decision per task class), `structlog_config` 100MB/7d.
- **W1 archived** — `(app)/research/[symbol]/+page.svelte` "loading…" stub with `meta` export so Sidebar enumerates it; `useFetch` + `useSSE` composables; design tokens locked in DESIGN.md §1; lucide-svelte icons; 8 SSE consumer stubs at `lib/sse/*.ts` including `research.ts`.
- **R2/R3/R4 IN FLIGHT** — may or may not be merged. R5 dev path uses `SourcePort` **fakes** at `tests/fakes/source_port_fakes.py` (`FakeEdgarSource`, `FakeFinnhubSource`, `FakeOpenBBSource` returning canned `ResearchFactDraft` for AAPL/NVDA/SPY corpora) so the integration test does not block on sibling-slice merge. Production deployment is order-independent — R5's `service.py` queries the repository for facts (the adapters wrote them already, regardless of which slice merged first).

The challenge is **breadth + cross-domain integration**, not a single hard problem. R1 already settled the schema. O1 already settled the LLM cost contract. W1 already settled the design tokens. R5's job is to wire all three together correctly + ship 5 methodologies + the 5 components without divergence from the locked component contracts in [docs/ux/components.md §4.1-§4.5](../../../docs/ux/components.md#4-research-domain-components-journey-3).

## Goals / Non-Goals

**Goals:**
- Land 5 methodology pure functions producing deterministic `MethodologyResult` (ranking + score + rationale) for the same feature input, callable by both the synthesizer and unit tests.
- Land tier-aware `feature_provider` returning a `FeatureBundle` (dict[str, Decimal | None]) where every value carries its tier (A/B/C) — Tier-B values fail-loud in backtest queries via the CI assertion.
- Land `synthesizer.py` orchestrating `feature_provider → methodology → LLM (via O1 ObservabilityClient) → citation parse → audit_trail persist → brief insert` with retry-on-version-collision per R1 D5.
- Land `citation_resolver.py` parsing `[fact:<uuid>]` markers with the regex contract locked in j3.md §9 and resolving to `research_facts` rows; broken markers surface as `Badge variant="warn"` (NFR-O8).
- Land `audit_trail.py` + `0008_research_audit.py` migration so every LLM call (input prompt + output + token count + USD cost + duration_ms + model_id) persists for compliance replay; append-only L1 + L2 per slice 3 D3 contract.
- Land 5 components matching [components.md §4.1-§4.5](../../../docs/ux/components.md#4-research-domain-components-journey-3) verbatim — same prop shapes, same states, same tokens, same storybook stories list.
- Land `/research/[symbol]/+page.svelte` and `/research/[symbol]/audit-trail/[brief_version]/+page.svelte` matching j3.md §3 Steps 2-3 verbatim.
- Hit NFR-P9 (refresh < 30s p95) + NFR-O8 (every brief claim resolved or marked broken) + Lighthouse a11y ≥ 95.
- Maintain anti-collision: edit only files inside R5's worktree (no edits to `routes/__init__.py`, `sse/__init__.py`, `cli/main.py`, `Sidebar.svelte`, `app.py`, `migrations/env.py`, `shared/errors.py`).

**Non-Goals:**
- No Hindsight recall step in synthesizer — R6 wires it behind the feature flag.
- No O2 cron scheduling of brief refresh — `BriefService.refresh()` is callable; O2 wires the cron triggers.
- No T4 trading FK population — `trade_proposals.research_brief_id` is consumed (read-only) but not written by R5.
- No PDF weekly review generation — O2.
- No as-of replay UI on `/research/[symbol]?as_of=<ts>` — DEFERRED to v1.5 per proposal scope; route accepts the param but renders latest brief + TBD banner.
- No Pattern Observation archive (`/research/insights`) — R6.
- No new Python or JS deps.

## Architecture diagram

```
                     ┌────────────────────────────────────────────────────────────────┐
                     │  POST /research/briefs/{symbol}/refresh   (slowapi 5/min)      │
                     │  GET  /research/briefs/{symbol}                                 │
                     │  GET  /research/briefs/{brief_id}/audit-trail                   │
                     │  GET  /research/facts/{symbol}                                  │
                     │  SSE  /stream/research (publishes 3 events)                     │
                     └──────────────────────────┬─────────────────────────────────────┘
                                                │
                                  ┌─────────────▼─────────────┐
                                  │  contexts/research/        │
                                  │      service.py            │
                                  │  BriefService.refresh()    │
                                  │  - rate-limit gate         │
                                  │  - retry-on-collision (D5) │
                                  └─────────────┬─────────────┘
                                                │
        ┌───────────────────────────────────────┼────────────────────────────────────────┐
        │                                       │                                        │
┌───────▼────────┐                ┌─────────────▼─────────────┐                ┌─────────▼────────┐
│ feature_       │                │  synthesis/synthesizer.py  │                │  scheduler.py     │
│ provider/      │                │  1. fetch features         │                │  - cron hooks     │
│  tier_a.py     │  features ──▶  │  2. methodology.score()    │                │    (O2 wires)     │
│  tier_b.py     │  bundle        │  3. fill prompt template   │                │  - on-trigger     │
│  tier_c.py     │                │  4. ObservabilityClient    │  ◀───── LLM    │    on fact-event  │
└───────┬────────┘                │     (O1: cost_meter,       │                └───────────────────┘
        │                         │      replay_cache, budget) │
        │                         │  5. parse [fact:<uuid>]    │
   reads research_facts via       │  6. audit_trail.persist()  │
   ResearchRepository.as_of()     │  7. citation_resolver.bind │
        │                         │  8. repository.insert_brief│
        │                         └─────────────┬──────────────┘
        │                                       │
   ┌────▼────────────────────────┐    ┌─────────▼──────────────────────────┐
   │  R1 ResearchRepository       │    │  audit_trail.py                    │
   │  - as_of(symbol, at)         │    │  + research_audit_trail (NEW)      │
   │  - insert_fact(draft)        │    │  - append-only L1 + L2 (mig 0008)  │
   │  - supersede_fact(id, at)    │    │  - one row per LLM call            │
   │  - latest_brief(symbol)      │    └────────────────────────────────────┘
   │  - insert_brief(...) [R5]    │
   └──────────────────────────────┘
                                  ───── ResearchBriefSynthesized event ─────▶ MessageBus
                                                                               (R6 subscribes)

────────────────────────────────────────────────────────────────────────────────────────────────────
                                       FRONTEND (apps/web)
────────────────────────────────────────────────────────────────────────────────────────────────────
   /research/[symbol]/+page.svelte                    /research/[symbol]/audit-trail/[v]/+page.svelte
        │                                                          │
   ┌────▼─────┐ ┌──────────┐ ┌────────────┐                ┌───────▼──────────┐ ┌────────────────┐
   │BriefHeadr│ │FactTimlin│ │CitationLink│                │AuditTrailViewer  │ │CitationLink    │
   └──────────┘ └──────────┘ └────────────┘                │  + MethodBadge   │ │  + MethodBadge │
                                                           └──────────────────┘ └────────────────┘
   Composes: lib/research/render-brief.ts (parses [fact:<uuid>] → CitationLink Svelte components)
   useFetch /api/v1/research/briefs/<symbol>  +  useSSE /api/v1/stream/research
```

## Decisions

### D1. Methodologies are pure functions returning a typed `MethodologyResult`, NOT class hierarchies

**Decision**: each methodology lives in `methodology/<name>.py` exporting one top-level function `score(features: Mapping[str, Decimal | None]) -> MethodologyResult` where `MethodologyResult` is a `dataclass(frozen=True, slots=True)` with fields `(overall_score: Decimal, ranking: int, pillars: dict[str, PillarScore], rationale: str, missing_features: list[str])`. Pure-functional: same input → same output, no I/O, no globals. The synthesizer composes: features come from `feature_provider`, `MethodologyResult` is fed into the prompt template, the LLM narrates the rationale into prose. Methodology unit tests assert determinism via snapshot fixtures keyed on canonical feature inputs (e.g. AAPL 2026-04-01 fundamentals).

**Alternatives considered**:
- **Class hierarchy `MethodologyBase` + 5 subclasses**: cleaner OO but no shared state across methodologies — methodology bodies don't compose; each is independent. Rejected — pure functions match FR58's "callable framework" intent better.
- **LangChain `Chain` per methodology**: defers methodology logic to LLM prompts; loses determinism + makes unit testing impossible without LLM calls. Rejected — methodology MUST be deterministic; LLM is for prose narration only.
- **YAML/JSON-driven methodology config**: declarative scoring rules in config files. Considered for future extensibility, but MVP needs 5 fixed methodologies with research-paper-grade fidelity (William O'Neil 7-criteria CANSLIM, Greenblatt 2-criterion Magic Formula, etc.) — code captures the nuance better than config. Rejected; revisit in v2.

**Rationale**: pure-function determinism + clear unit-test contract + obvious testability (hypothesis property tests on bounded inputs trivial). Synthesizer treats methodology as a black box.

### D2. Feature provider is tier-aware via composition, NOT enum dispatch

**Decision**: `feature_provider/base.py` defines `FeatureBundle = dict[str, FeatureValue]` and `FeatureValue = (Decimal | None, Tier)` (`Tier` is `Literal["A","B","C"]`). Three concrete providers compose:
- `tier_a.py::TierAFeatureProvider` reads native-PiT fact kinds from R1 (EDGAR XBRL: `eps_diluted`, `revenue`; FRED: `cpi_yoy`, `unemployment_rate`; IBKR bars: `close`, `volume`). Always returns `(value, "A")` or `(None, "A")`.
- `tier_b.py::TierBFeatureProvider` reads snapshot-collected fact kinds (Finnhub news sentiment, GDELT events, OpenInsider scrapes). Returns `(value, "B")` only if `recorded_from <= since` constraint holds; else `(None, "B")`.
- `tier_c.py::TierCFeatureProvider` reads bootstrap fact kinds (WGI governance, V-Dem democracy index). Returns `(value, "C")` only at the bootstrapped timestamp; else `(None, "C")`.

A `CompositeFeatureProvider` aggregates the three providers per methodology recipe (e.g., CANSLIM needs `[eps_growth_yoy:A, sales_growth_yoy:A, new_high_52w:A, sector_strength:A, mgmt_holdings:B, ipo_age:A, market_trend:A]`).

**CI assertion** (`tests/unit/contexts/research/test_feature_provider_tier.py`): uses `ast.parse` to walk every file under `apps/api/src/iguanatrader/contexts/trading/strategies/` (T3 + future T4 backtest hot path) and FAILS the test if any code path queries `TierBFeatureProvider` without an explicit `since: datetime` argument. Implementation: collect call-graph edges to `tier_b.fetch(...)`; assert each call site's `since` kwarg is non-default.

**Alternatives considered**:
- **Single `FeatureProvider` with `tier: Tier` parameter**: collapses three classes into one + an enum dispatch. Loses the type-narrowing benefit (callers can't tell which provider's `since` semantics apply). Rejected.
- **`Tier` baked into the column** on `research_facts`: actually the schema already carries `tier` (R1 data-model §3.7), but tier-routing happens at query time, not row time — the provider chooses which fact kinds to request. The column is the source of truth; the provider is the dispatcher.
- **Runtime check** (raise on Tier-B usage in backtest contextvar): no compile-time guarantee; CI assertion via `ast.parse` is preferred — fails before merge.

**Rationale**: composition + AST-level CI assertion gives the strongest guarantee with zero runtime overhead. FR75's "strategy code MUST handle None returns gracefully" is enforced by the type signature (`Decimal | None`).

### D3. Synthesizer orchestrates a 7-step pipeline; LLM is consulted ONCE per refresh; citations come from a typed bundle, NOT from re-asking the LLM

**Decision**: `BriefService.refresh(symbol, methodology)` runs:

1. **Acquire rate-limit slot** via slowapi (5/min per tenant; same pattern as `/auth/login`).
2. **Fetch features** via `CompositeFeatureProvider.fetch(symbol, methodology)` → `FeatureBundle`. Each value carries its tier + source `fact_id` (the resolver later uses these).
3. **Score methodology** via `methodology.score(feature_bundle.values_only())` → `MethodologyResult`.
4. **Render prompt** by filling `synthesis/prompts/<methodology>.md` Jinja2 template with: `{symbol, methodology_result, feature_bundle, fact_citations}`. Template instructs the LLM: (a) cite every numeric claim with `[fact:<uuid>]` markers using ONLY UUIDs from the provided `fact_citations` list — invented UUIDs forbidden; (b) emit prose pillar-by-pillar; (c) emit JSON `audit_trail_entries` for any computed metric (P/E ratio, growth rate, etc.) with formula + inputs + intermediate steps + final output; (d) emit `partial=true` if any feature is `None` AND tier is A.
5. **Invoke LLM** via `iguanatrader.contexts.observability.ObservabilityClient.complete(prompt, task_class="research_brief", replay_key=f"brief:{symbol}:{methodology}:{feature_hash}")`. The `task_class` drives O1's `llm_routing` (likely Sonnet for synthesis); `replay_cache` returns cached output if `replay_key` matches a prior call (deterministic for tests + cost-saving for re-renders); `cost_meter` ledgers the call; `budget` raises `BudgetExceededError` if monthly cap hit.
6. **Parse output**: extract markdown body + JSON audit_trail_entries. Validate `[fact:<uuid>]` markers against `feature_bundle.fact_citations` keys — invented UUIDs raise `InvalidCitationError` and the synthesis fails (no silent corruption).
7. **Persist**: open a single transaction. Insert `research_briefs` row (R1 D5 retry-on-version-collision, max 3 attempts). For each audit_trail_entry, insert `research_audit_trail` row. Emit `ResearchBriefSynthesized` event on the bus. Commit.

The LLM is invoked **exactly once** per refresh; citations are provided in the input AND validated on the output. The renderer does NOT re-ask the LLM for citation metadata — `citation_resolver.py` reads `research_facts` directly.

**Alternatives considered**:
- **Two-pass synthesis** (LLM drafts → second LLM call resolves citations): doubles cost + introduces non-determinism in the resolution step. Rejected.
- **Stream the LLM output token-by-token through SSE**: nice UX but breaks atomic transaction semantics — partial brief visible mid-flight. Rejected for MVP; SSE only emits coarse-grained `progress` events (`step=fetching_features`, `step=invoking_llm`, `step=parsing_citations`, `step=persisting`); the brief itself is visible only after commit.
- **Skip the methodology pure-function step + ask LLM to score**: collapses determinism. Rejected per D1.

**Rationale**: single LLM call + strict citation contract = deterministic citation chain (NFR-O8) + bounded cost (NFR-P9) + clear failure mode (`InvalidCitationError` is loud, not silent).

### D4. Citation marker syntax is `[fact:<uuid>]` (UUID, NOT integer); marker UUIDs MUST be in the LLM's input bundle

**Decision**: every `research_fact` in the feature bundle carries its `id: UUID`. The prompt template embeds them as a numbered list with the canonical UUID. The LLM cites with `[fact:<uuid>]` (verbatim per j3.md §9 resolved 2026-05-05). Renderer regex: `/\[fact:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\]/gi`.

**Why UUID, not integer**:
- Integer ids would collide across briefs (e.g., "fact 42" in brief A is a different fact from "fact 42" in brief B); UUID is globally unique.
- Citations may travel between contexts (brief → trade_proposal.reasoning JSON → audit log); UUID preserves identity across copies.
- LLM-invented UUIDs are unlikely to coincidentally match real ones; integer-collision risk is much higher in a hallucinating model.

The `citation_resolver.py` validates each parsed UUID against `research_facts.id` for the brief's tenant. Unresolved → broken-citation `Badge variant="warn"` (per components.md §4.3 edge case) AND structlog event `research.citation.broken` AND CI integration test fails.

**Alternatives considered**:
- **Footnote-map sidecar** (`[1]`, `[2]` in body + JSON map at end): more compact prompts but adds an extra parse step + breaks if the LLM emits `[3]` without a corresponding map entry. Rejected.
- **Markdown link syntax `[claim](fact:<uuid>)`**: works but conflicts with regular links in the brief body. Rejected.
- **HTML span with data-fact-id**: works but couples the prompt to the rendering layer. Rejected.

**Rationale**: locked in j3.md §9. Validated mock at `docs/ux/variants/mock-j3-2-citation-syntax.html`.

### D5. `audit_trail` is a dedicated table, NOT a JSON column on `research_briefs`

**Decision**: migration `0008_research_audit.py` creates `research_audit_trail`:
```
id UUID PK
tenant_id UUID NOT NULL  (slice-3 listener injects)
brief_id UUID NOT NULL FK research_briefs(id) ON DELETE RESTRICT
brief_version INTEGER NOT NULL  (denormalised for query performance)
metric VARCHAR(64) NOT NULL  ('forward_pe', 'eps_growth_yoy', ...)
formula TEXT NOT NULL  ('price / forward_eps')
inputs JSONB NOT NULL  ([{name, value, fact_id}, ...])
steps JSONB NOT NULL  ([{description, intermediate}, ...])  -- empty array for one-shot lookups
final_output TEXT NOT NULL
methodology VARCHAR(32) NOT NULL  ('canslim' | '3-pillar' | ...)
llm_call_id UUID NOT NULL  (FK to api_cost_events from O1; the LLM call that emitted this entry)
created_at TIMESTAMPTZ NOT NULL DEFAULT now()
```

Append-only at L1 (`__tablename_is_append_only__ = True`) + L2 (BEFORE UPDATE/DELETE trigger per slice-3 D3). Indexes: `(tenant_id, brief_id)`, `(tenant_id, metric)`. FK `llm_call_id` references O1's `api_cost_events` so the audit row is one click from the per-call cost ledger.

**Alternatives considered**:
- **JSONB column `audit_trail JSONB` on `research_briefs`**: collapses storage but breaks query patterns (e.g., "all briefs that cited fact X" requires JSONB path navigation, slow even with GIN index). Rejected.
- **Materialised view**: premature optimisation; revisit if query patterns demand it.
- **Per-LLM-call denormalisation** (one row per LLM call across all briefs): we already have `api_cost_events` from O1 for this; `research_audit_trail` is the **research-domain shape** of the same call linked back to brief_id + metric.

**Rationale**: separate table = cleaner queries + cleaner indexes + cleaner append-only enforcement. The FK to `api_cost_events` ties the audit (research view) to the cost ledger (observability view) without duplication.

### D6. `BriefResponse` shape extends R1's DTO; `audit_trail_summary` is computed at API time

**Decision**: R1 shipped `BriefResponse` with `(id, symbol, version, methodology, synthesized_at, thesis_text, score_overall, citations: list[CitationDetail], audit_trail: list[AuditTrailEntry])`. R5 EXTENDS in-place (additive — no removed fields, no renamed fields):
- `body_markdown: str` — raw brief markdown with `[fact:<uuid>]` markers (frontend renderer parses).
- `pillar_scores: dict[str, Decimal]` — methodology pillars (e.g., for CANSLIM: `{"C": 0.8, "A": 0.6, ...}`).
- `audit_trail_summary: dict[str, int]` — `{metric_count: int, llm_calls: int, partial: bool}` (frontend uses for header badge; full detail at `/audit-trail/<version>`).
- `next_scheduled_refresh_at: datetime | None` — populated when O2 cron is wired; null in MVP-R5.
- `last_fact_recorded_at: datetime` — most recent `research_facts.recorded_from` for the symbol; freshness signal.

`/audit-trail/{brief_id}` returns `list[AuditTrailEntry]` directly (the full audit list). `/research/facts/{symbol}` returns `list[FactResponse]` for FactTimeline.

**Alternatives considered**:
- **Embed full `audit_trail` in `BriefResponse`**: works but inflates response by ~50KB for a CANSLIM brief with 8 metrics. Frontend doesn't need detail until the user clicks audit-trail link. Rejected.
- **Add `audit_trail_url`**: REST-y but adds a redirect step. The current design (summary in `BriefResponse`, full detail at separate endpoint) matches j3.md §3 navigation.

**Rationale**: minimal additive surface; OpenAPI typegen regenerates `packages/shared-types/src/index.ts` automatically; frontend uses both endpoints.

### D7. Frontend brief markdown renderer is a custom pipeline, NOT a generic markdown library

**Decision**: `apps/web/src/lib/research/render-brief.ts` is a custom renderer that:
1. Sanitises the brief markdown via DOMPurify (LLM output is untrusted).
2. Parses with `marked` (already a transitive dep via lucide-svelte? no — added in this slice as `marked@^14` + `dompurify@^3` — checked: both are tiny + Apache/MIT compatible with our license boundary).
3. Walks the resulting AST and replaces text nodes containing `[fact:<uuid>]` markers with mounted `CitationLink.svelte` components (resolved against the brief's `citations` payload).
4. Emits `<h2>` per methodology pillar, `<h3>` per sub-section, `<p>` for prose. Custom token handlers for the `[fact:<uuid>]` substitution.

**Alternatives considered**:
- **`mdsvex`** (Svelte-native MDX): requires the brief markdown to be in the build pipeline, which it isn't (LLM-generated at runtime). Rejected.
- **`svelte-markdown`** library: doesn't expose AST hooks for custom token replacement. Rejected.
- **Server-side render to HTML + send HTML to client**: defeats the typegen contract + makes citation hover-tooltips harder. Rejected.

**Rationale**: small custom renderer (~80 LOC) gives us total control over the citation substitution + DOMPurify sanitisation. Tests exercise the parser against fixture briefs.

**New deps**: `marked@^14` (MIT) + `dompurify@^3` (MPL-2.0/Apache-2.0 dual). License boundary check passes (Apache+CC repo accepts MIT/Apache compatible deps; MPL-2.0 is acceptable per SPDX scanner config from slice 1).

### D8. SSE publishes coarse-grained progress events, NOT token-streaming

**Decision**: `api/sse/research.py` emits 3 event types:
- `research.brief.refresh.progress` — payload `{symbol, step: "fetching_features"|"invoking_llm"|"parsing_citations"|"persisting", percent: 0-100, brief_version_in_flight: int}`. Emitted at step boundaries during synthesis.
- `research.brief.refreshed` — payload `{symbol, brief_id, brief_version, methodology, synthesized_at, partial: bool}`. Emitted after commit.
- `research.fact.recorded` — payload `{symbol, fact_id, source_id, fact_kind, recorded_from}`. Subscribed via the bus (`ResearchFactIngested` event from R1) and published to SSE for `FactTimeline` live updates.

**Alternatives considered**:
- **Token-streaming the LLM output**: O1's `ObservabilityClient` doesn't expose stream callbacks (cost meter ledger is per-completion); adding it would require Wave-3 of O1. Rejected for MVP.
- **No SSE — poll instead**: violates W1's `useSSE` contract + creates jitter on the dashboard "refreshing" state.

**Rationale**: matches j3.md §3 Step 2 "header shows refreshing state with Spinner" semantics; refreshed event triggers BriefHeader version transition.

### D9. Replay determinism: citations are deterministic; brief PROSE is LLM-stochastic

**Decision**: O1's `replay_cache` keys by `(model_id, prompt_hash, params_hash)` — same inputs → cached output. R5 uses `replay_key=f"brief:{symbol}:{methodology}:{feature_hash}"` where `feature_hash = sha256(canonical(feature_bundle))`. In tests + retros + CI, the same feature input + methodology + model produces the same brief verbatim → deterministic replay. **In production**, two refreshes of the same brief with new facts (different `feature_hash`) may produce different prose; **the citation chain (set of `fact_id`s referenced) is constrained by the input bundle**, so the citations are deterministic given the bundle, even when prose varies.

**Caveat documented in NFR-O8 spec scenario**: "Given a brief and original facts, regenerating must yield identical brief (modulo LLM stochasticity caveat — replay_cache via O1 covers determinism in tests)". CI gates regression via replay_cache — a methodology change that produces a different brief with the same inputs fails the snapshot test.

**Alternatives considered**:
- **`temperature=0` only**: not enough for full determinism (some providers still vary tokenisation). Rejected — replay_cache is the canonical mechanism per O1.
- **Hash-pin the LLM provider+model+version**: O1's `llm_routing` already pins this per task_class. Documented in test fixtures.

**Rationale**: matches O1's contract + makes tests reproducible + makes the citation chain (the load-bearing part) deterministic-by-construction.

### D10. Failure modes: graceful degradation > hard failure

**Failure mode matrix**:

| Failure | Detection | Behaviour |
|---|---|---|
| LLM provider down (Anthropic 5xx, network drop) | `ObservabilityClient.complete` raises `LLMUnavailableError` | `BriefService.refresh` catches → returns the most recent immutable brief from `latest_brief()` with a `stale=true` flag in the response + structlog event `research.brief.refresh.failed.llm_unavailable`. Toast on frontend per j3.md §3 Step 2 edge case. |
| LLM cost would exceed monthly budget | `ObservabilityClient.complete` raises `BudgetExceededError` (O1) | 429 RFC 7807 with `type="urn:iguanatrader:error:budget-exceeded"` + retry_after. Frontend shows tooltip "Today's LLM budget exhausted — refresh queued for next budget window" (j3.md §3 Step 2 edge case). |
| Source data missing (e.g., EDGAR not yet ingested for symbol) | `feature_provider` returns `None` for tier-A required features | Methodology emits "insufficient data" with explicit list of missing tier-A features in `MethodologyResult.missing_features`. Brief still synthesises with `partial=true` flag; pillar shows "no data available at this knowledge-time" copy per j3.md §6 edge case. |
| LLM emits invented UUID in `[fact:<uuid>]` | `citation_resolver` validation fails | Synthesis ABORTS with `InvalidCitationError`; no brief persisted; structlog `research.synthesis.failed.invalid_citation` (loud, not silent). Tests assert this path. |
| Brief refresh hits version-collision race (D5) | `IntegrityError` on unique index | Repository retries up to 3 times (R1 D5); max retries → `BriefRefreshConflictError` → frontend shows "Refresh in progress in another tab — retry in 5s". |
| `research.fact.recorded` fires during in-flight refresh | Race between feature fetch and fact ingestion | The fetched bundle is a snapshot; the in-flight refresh uses it. The new fact triggers a follow-up refresh schedule via the bus subscriber (FR72 on-trigger). No silent loss. |
| Broken citation in synthesised brief (fact deleted? — append-only forbids, but `effective_to <= now` could be the issue) | `citation_resolver` returns `broken=true` for that marker | UI renders `Badge variant="warn"` per components.md §4.3; structlog `research.citation.broken` event; CI integration test fails on the test corpus to prevent regression. |

**Rationale**: graceful where the user can recover (LLM down → stale brief is still useful; budget hit → wait); hard where data integrity is at stake (invented citation → no brief). Matches JTBD-4's anti-hallucination contract.

## Risks / Trade-offs

- **[Risk] LLM cost runaway** — a methodology bug causing repeated refresh loops could blow through monthly budget in hours. **Mitigation**: O1's `budget` enforces per-tenant monthly cap; rate-limit slowapi 5/min per refresh endpoint; structlog event `research.brief.refresh.requested` rate-tracked in cost dashboard. Documented in gotchas.md #50.
- **[Risk] Citation marker UUID collision** — extremely unlikely (UUID v4) but theoretically possible: LLM hallucinating a UUID that happens to match a real fact in another tenant's data. **Mitigation**: `citation_resolver` validates against the brief's tenant's facts only (slice-3 tenant listener auto-injects `tenant_id` filter); cross-tenant resolution is structurally impossible. Documented in gotchas.md #51.
- **[Risk] Audit replay non-determinism** — different LLM model versions producing different briefs from same feature input. **Mitigation**: O1's `llm_routing` pins model_id + version per task_class; `replay_cache` key includes model_id; CI snapshot tests detect drift before deploy. NFR-O8 caveat documented in the spec.
- **[Risk] Methodology fidelity** — CANSLIM's 7 criteria are nuanced (e.g., "M = market direction" requires looking at SPY trend, not just the symbol). Risk: simplistic implementation that "passes tests" but is research-paper-unfaithful. **Mitigation**: each methodology file's docstring cites the canonical source (William O'Neil 2002 "How to Make Money in Stocks"; Greenblatt 2005 "The Little Book That Beats the Market"); unit tests include "known answer" fixtures (e.g., AAPL 2023 Q1 features → expected CANSLIM ranking) sourced from the books. Reviewer (Arturo) signs off the fixtures.
- **[Risk] Tier-B usage in backtest features sneaks past CI assertion** — `ast.parse` walking is brittle to refactors (e.g., dynamic dispatch via `getattr`). **Mitigation**: assertion is conservative — flags ANY `tier_b.fetch(...)` call in `strategies/`; explicit allow-list comment `# allow-tier-b-in-backtest: <reason>` required for false positives. Rare in MVP; likely zero allowlist entries.
- **[Trade-off] `marked@^14 + dompurify@^3` adds 2 frontend deps** — both are small (~30KB combined gzipped) + license-compatible. Alternative is hand-rolled markdown parser (more LOC, more bugs). Trade-off favours the deps.
- **[Trade-off] Audit trail table grows unbounded** — every brief × every metric × every LLM call. For a single user with 50 symbols × weekly refresh × 8 audit entries/brief = ~21k rows/year. Negligible. v2 SaaS may need archival policy at 10k+ tenants × 100+ symbols.
- **[Trade-off] Methodology rationale is in code, not config** — adding a 6th methodology requires a code PR. Acceptable for MVP (5 fixed); v1.5 may extract to YAML if a 6th demanded.

## Migration Plan

R5 has no live deployment to migrate from. Deployment path:

1. Land R1 archived ✓ (2026-05-06).
2. Land O1 archived ✓ (2026-05-06).
3. Land W1 archived ✓ (2026-05-06).
4. R5 branches from main; develops with `SourcePort` fakes for R2/R3/R4 (parallel siblings).
5. Migration `0008_research_audit.py` runs in-line with R5's deploy; `down_revision = "0007"` (O1's observability tables).
6. R5 PR merges. CI typegen regenerates `packages/shared-types/src/index.ts` with extended `BriefResponse`.
7. R6 branches from main and adds Hindsight recall step in synthesizer (D8 in R6 design); R5's no-recall path is the baseline.
8. T4 branches from main and writes `trade_proposals.research_brief_id` FK consuming R5's `BriefResponse.id`.
9. O2 branches from main and wires cron schedules calling `BriefService.refresh()` from R5.

Rollback = revert PR + Alembic `downgrade -1` (drops `research_audit_trail` table + trigger). Briefs persisted under R5 stay (they are in `research_briefs` from R1's schema); only the audit trail is lost. Re-applying R5 + replay from `replay_cache` regenerates the audit trail for any briefs synthesised post-rollback.

## Open Questions

- **Q**: Should `feature_provider` cache its bundles (per-symbol + per-methodology + per-tenant) for the rate-limit-window? **Tentative answer**: NO for MVP — per-refresh fetch is bounded (50 symbols × 7 features × ~20ms/query = 7s; well under NFR-P9 30s budget). v1.5 revisits if NFR-P9 is missed in production load.
- **Q**: Should the `body_markdown` in `BriefResponse` be the raw LLM output or the renderer-normalised HTML? **Tentative answer**: raw markdown — frontend renderer owns the substitution + sanitisation; sending HTML server-side would force the server to import DOMPurify (adds an OOB dep). Documented in D7.
- **Q**: How does the synthesizer handle a methodology that produces a brief shorter than ~200 words (LLM hallucinated nothing useful)? **Tentative answer**: add a CHECK on `BriefService.refresh` post-LLM that asserts `len(body_markdown.split()) >= 100`; below threshold → `BriefSynthesisShortError`, no persist. Pragma — adjustable in v1.5 based on observed corpora.
- **Q**: Does `audit_trail` need to capture the `feature_bundle` snapshot (the inputs to the methodology pure function)? **Tentative answer**: YES — store as JSONB on `research_briefs` (not a new column; reuse R1's `audit_trail JSONB` column from data-model §3.7 if present, else add). This makes "given a brief and original facts, regenerating yields identical brief" testable end-to-end. Confirm column presence in R1's schema during task 1.x; add column in `0008_research_audit.py` if missing.
