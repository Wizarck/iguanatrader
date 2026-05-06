## ADDED Requirements

### Requirement: 5 research methodologies are pure-function deterministic frameworks

The system SHALL ship five research methodologies — `3-pillar`, `canslim`, `magic-formula`, `qarp`, `multi-factor` — each as a pure function `score(features: Mapping[str, Decimal | None]) -> MethodologyResult`. Each function SHALL be deterministic (same input → same output), free of side effects (no I/O, no globals), and pinned to a documented research source (William O'Neil 2002 for CANSLIM; Greenblatt 2005 for Magic Formula; Fama-French 2015 for Multi-factor; etc.). The `MethodologyResult` SHALL carry `(overall_score: Decimal, ranking: int, pillars: dict[str, PillarScore], rationale: str, missing_features: list[str])`. All score values SHALL be `Decimal`, never float. The system SHALL expose a `METHODOLOGY_REGISTRY: dict[str, Callable]` mapping methodology slug to its `score` function.

#### Scenario: 3-pillar score is deterministic

- **GIVEN** a fixed feature bundle `{eps_growth_yoy: Decimal("0.18"), revenue_growth_yoy: Decimal("0.22"), forward_pe: Decimal("22.4"), pb_ratio: Decimal("4.1"), dividend_yield: Decimal("0.012"), return_3m: Decimal("0.07"), return_12m: Decimal("0.31"), relative_strength: Decimal("78")}`
- **WHEN** `methodology.three_pillar.score(features)` is invoked twice in the same process
- **THEN** both invocations return MethodologyResult with identical `overall_score`, `ranking`, and per-pillar scores
- **AND** invoking the same function in a fresh process with the same input yields the identical result
- **AND** all numeric values in the result are `Decimal` (no float coercion)

#### Scenario: CANSLIM with missing tier-A feature surfaces in `missing_features`

- **GIVEN** a CANSLIM-required feature bundle where `current_quarter_eps_growth` is `None`
- **WHEN** `methodology.canslim.score(features)` is invoked
- **THEN** the result carries `missing_features=["current_quarter_eps_growth"]`
- **AND** the C pillar's `PillarScore.score` is `Decimal("0")` (no contribution)
- **AND** `overall_score` reflects the lower contribution
- **AND** the `rationale` text includes "C pillar: data unavailable"

#### Scenario: Magic Formula computes EBIT/EV + ROC ranking per Greenblatt 2005

- **GIVEN** a feature bundle with `ebit_yield = Decimal("0.082")` and `return_on_capital = Decimal("0.245")`
- **WHEN** `methodology.magic_formula.score(features)` is invoked
- **THEN** the result's `pillars["ebit_yield"].score` and `pillars["return_on_capital"].score` reflect the values
- **AND** the `overall_score` equals the documented Greenblatt rank-sum formula (canonical ref in module docstring)

### Requirement: Feature provider classifies every value by tier (A/B/C) with CI-blocking enforcement

The system SHALL implement three tiered feature providers — `TierAFeatureProvider` (native PiT: EDGAR XBRL, FRED, IBKR bars), `TierBFeatureProvider` (snapshot collected: Finnhub news, GDELT, OpenInsider), `TierCFeatureProvider` (one-shot bootstrap: WGI, V-Dem) — each returning `FeatureValue = (Decimal | None, Tier)` with `Tier = Literal["A", "B", "C"]`. A `CompositeFeatureProvider` SHALL aggregate the three providers per methodology recipe. The system SHALL provide a CI-blocking unit test `test_feature_provider_tier.py` that walks `apps/api/src/iguanatrader/contexts/trading/strategies/**/*.py` via `ast.parse` and FAILS the test if any `tier_b.*` call site lacks an explicit non-default `since` kwarg, with allow-list comment `# allow-tier-b-in-backtest: <reason>` for false positives.

#### Scenario: Tier-A feature provider returns native PiT value

- **GIVEN** a `research_facts` row for AAPL with `fact_kind="eps_diluted"`, `value_numeric=Decimal("1.52")`, `effective_from=2026-01-25T00:00Z`, `tier="A"`
- **WHEN** `TierAFeatureProvider.fetch(symbol="AAPL", since=None)` is invoked at knowledge-time 2026-04-01
- **THEN** the returned bundle contains `("eps_diluted", (Decimal("1.52"), "A"))`
- **AND** `bundle.fact_citations["eps_diluted"]` resolves to the fact's UUID

#### Scenario: Tier-B feature provider rejects backtest query without `since`

- **GIVEN** a strategy file `apps/api/src/iguanatrader/contexts/trading/strategies/donchian_atr.py` that imports `TierBFeatureProvider` and calls `provider.fetch(symbol)` (no `since` kwarg)
- **WHEN** `pytest apps/api/tests/unit/contexts/research/test_feature_provider_tier.py` runs
- **THEN** the test FAILS with a clear message identifying the file + line of the offending call
- **AND** the message references FR75 + the allow-list comment escape hatch
- **AND** CI blocks the merge

#### Scenario: Tier-C bootstrap-only timestamp constraint

- **GIVEN** a `research_facts` row with `tier="C"`, `recorded_from=2025-01-01T00:00Z` (the bootstrap moment), `fact_kind="vdem_democracy_index"`
- **WHEN** `TierCFeatureProvider.fetch(symbol="AAPL", since=2024-06-01T00:00Z)` is invoked at knowledge-time 2024-12-31
- **THEN** the bundle contains `("vdem_democracy_index", (None, "C"))` — value not yet bootstrapped
- **AND** at knowledge-time 2026-01-01, the same call returns `(Decimal("0.74"), "C")`

### Requirement: `[fact:<uuid>]` citation markers in brief body MUST resolve to a `research_facts` row in the same tenant; broken markers fail the render

The system SHALL embed citations in `research_briefs.body_markdown` using the syntax `[fact:<uuid>]` where `<uuid>` is a canonical UUID v4 string. The `CitationResolver.resolve(brief)` method SHALL parse the body with regex `\[fact:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\]` (case-insensitive), batch-fetch the referenced `research_facts` rows scoped to the brief's tenant_id, and return a `ResolvedBrief(body_markdown, citations: list[CitationDetail], broken_markers: list[str])`. Per NFR-O8, the resolver SHALL emit a structlog event `research.citation.broken` for every unresolved marker AND the system SHALL provide a CI integration test that fails the build if any brief in the test corpus contains broken_markers.

#### Scenario: Brief with valid citations resolves to full citation bundle

- **GIVEN** a synthesized brief `body_markdown="EPS grew 18% YoY [fact:550e8400-e29b-41d4-a716-446655440001] driven by Services revenue [fact:550e8400-e29b-41d4-a716-446655440002]"`
- **AND** both UUIDs match `research_facts.id` rows for the brief's tenant
- **WHEN** `CitationResolver.resolve(brief)` is invoked
- **THEN** the resolved bundle has `len(citations) == 2`
- **AND** `len(broken_markers) == 0`
- **AND** each `CitationDetail` carries `(fact_id, source_id, source_url, source_label, retrieved_at, retrieval_method)`
- **AND** `claim_excerpt` contains the surrounding 100-character text window for the citation

#### Scenario: LLM-invented UUID raises `InvalidCitationError` during synthesis (pre-persist)

- **GIVEN** the LLM returns a `body_markdown` containing `[fact:00000000-0000-0000-0000-000000000000]` not present in the input feature bundle's `fact_citations`
- **WHEN** `Synthesizer.synthesize(...)` validates markers
- **THEN** `InvalidCitationError` is raised
- **AND** the brief is NOT persisted (no `research_briefs` row, no `research_audit_trail` rows)
- **AND** structlog event `research.synthesis.failed.invalid_citation` is emitted with the offending UUID

#### Scenario: Cross-tenant citation attempt resolves as broken

- **GIVEN** a brief for tenant A whose body contains `[fact:<uuid>]` referencing a fact_id that exists ONLY for tenant B
- **WHEN** `CitationResolver.resolve(brief)` runs (slice-3 tenant listener filters by tenant A)
- **THEN** the citation appears in `broken_markers`, not in `citations`
- **AND** structlog event `research.citation.broken` is emitted
- **AND** the frontend renders the marker as `Badge variant="warn"` per components.md §4.3

### Requirement: Every LLM call during brief synthesis persists to `research_audit_trail`

The system SHALL persist every LLM call that contributes to a brief synthesis to the `research_audit_trail` table with columns `(id, tenant_id, brief_id, brief_version, metric, formula, inputs, steps, final_output, methodology, llm_call_id, created_at)`. The `llm_call_id` SHALL FK to `api_cost_events.id` (O1's per-call cost ledger) so the audit row is one click from the per-call cost detail. The table SHALL be append-only at L1 (`__tablename_is_append_only__ = True`) and L2 (BEFORE UPDATE / BEFORE DELETE triggers in migration `0008_research_audit.py`). The system SHALL provide a route `GET /api/v1/research/briefs/{brief_id}/audit-trail` returning the entries deterministically ordered (`ORDER BY created_at ASC, metric ASC`).

#### Scenario: Synthesizing a CANSLIM brief persists 8 audit_trail entries

- **GIVEN** a synthesizer run for AAPL with methodology="canslim" producing a brief with 8 computed metrics (one per CANSLIM letter)
- **WHEN** `BriefService.refresh()` completes successfully
- **THEN** `research_audit_trail` contains 8 rows with `brief_id=<new-brief-id>`, `methodology="canslim"`
- **AND** each row's `inputs` JSONB array references fact_ids present in the brief's input feature bundle
- **AND** each row's `llm_call_id` resolves to a single `api_cost_events` row (one LLM call shared across all 8 metrics — D3 contract)

#### Scenario: ORM UPDATE on research_audit_trail blocked by L1

- **GIVEN** a persisted `ResearchAuditTrail` row loaded into a session
- **WHEN** a caller mutates `instance.formula = "fake"` and calls `session.flush()`
- **THEN** the slice-3 `before_flush` listener detects the dirty instance
- **AND** raises `AppendOnlyViolationError` before reaching the driver

#### Scenario: Raw SQL DELETE on research_audit_trail blocked by L2

- **WHEN** a caller executes `session.execute(text("DELETE FROM research_audit_trail WHERE id = :id"), {"id": ...})`
- **THEN** the L2 BEFORE DELETE trigger fires and aborts the operation

### Requirement: `BriefService.refresh()` enforces version monotonicity, retry-on-collision, and rate-limiting

The system SHALL expose `BriefService.refresh(symbol, methodology) -> ResearchBrief` that orchestrates the synthesis pipeline (feature fetch → methodology score → LLM call → citation parse → audit persist → brief insert). The route `POST /api/v1/research/briefs/{symbol}/refresh` SHALL be rate-limited via slowapi to 5/minute per tenant. The service SHALL retry up to 3 times on `IntegrityError` due to per-symbol per-tenant `version` collision (R1 D5 contract). The new brief SHALL have `version = 1 + COALESCE(MAX(version) FILTERED by tenant_id + symbol_universe_id, 0)`. After successful insert, the service SHALL emit `ResearchBriefSynthesized` event on the MessageBus.

#### Scenario: First refresh creates version 1

- **GIVEN** a tenant with no existing `research_briefs` rows for symbol AAPL
- **WHEN** `BriefService.refresh(symbol="AAPL", methodology="3-pillar")` is invoked
- **THEN** the returned brief has `version = 1`
- **AND** `ResearchBriefSynthesized` event is emitted with `brief_id`, `version=1`, `methodology="3-pillar"`, `partial=false`

#### Scenario: 6th refresh in 60s returns 429

- **GIVEN** a tenant has invoked `POST /research/briefs/AAPL/refresh` 5 times within 60 seconds
- **WHEN** the 6th request arrives
- **THEN** the response is `429 Too Many Requests` (RFC 7807)
- **AND** the response body has `type="urn:iguanatrader:error:rate-limited"` and `retry_after` populated
- **AND** structlog event `api.research.refresh.rate_limited` is emitted

#### Scenario: Concurrent refresh hits version collision and retries

- **GIVEN** two refresh calls for the same `(tenant, symbol)` execute concurrently and both compute `version = 4`
- **WHEN** the second insert fails with `IntegrityError` on the unique constraint
- **THEN** `BriefService.refresh()` recomputes the next version and retries (max 3 attempts)
- **AND** the second call ultimately succeeds with `version = 5`
- **AND** if all 3 retries fail, the service raises `BriefRefreshConflictError` rendered as 409 RFC 7807

### Requirement: Brief refresh SSE publishes coarse-grained progress events

The system SHALL provide an SSE endpoint at `/api/v1/stream/research` (mounted via slice-5 dynamic discovery) that publishes three event types: `research.brief.refresh.progress` (during synthesis at step boundaries — fetching_features / invoking_llm / parsing_citations / persisting), `research.brief.refreshed` (after commit), and `research.fact.recorded` (subscribed from `ResearchFactIngested` MessageBus events).

#### Scenario: Refresh emits progress events at step boundaries

- **GIVEN** a connected SSE client subscribed to `/api/v1/stream/research`
- **WHEN** `POST /research/briefs/AAPL/refresh` is invoked and synthesis runs
- **THEN** the client receives 4 `research.brief.refresh.progress` events (one per step: fetching_features → invoking_llm → parsing_citations → persisting) with monotonic `percent` values 25, 50, 75, 100
- **AND** the client receives 1 `research.brief.refreshed` event with the new brief_id and version after commit

#### Scenario: New fact ingestion publishes to SSE

- **GIVEN** a connected SSE client
- **WHEN** an R2/R3/R4 source adapter inserts a new fact via `ResearchRepository.insert_fact()` and emits `ResearchFactIngested` on the bus
- **THEN** the client receives a `research.fact.recorded` event with `(symbol, fact_id, source_id, fact_kind, recorded_from)`

### Requirement: Brief refresh perf budget and cache hit ratio

The system SHALL complete a brief refresh in less than 30 seconds at p95 (NFR-P9). The system SHALL achieve a `replay_cache` hit ratio of at least 40% in steady-state (measured weekly), so repeated refreshes of the same `(symbol, methodology, feature_hash)` return cached LLM output without re-incurring cost. The CI suite SHALL include a pytest-benchmark gate on `BriefService.refresh()` against the source_port_fakes corpus.

#### Scenario: Refresh completes within 30s p95

- **GIVEN** a benchmark run of 10 sequential `BriefService.refresh()` calls against the source_port_fakes corpus with replay_cache enabled
- **WHEN** the benchmark measures wall-clock duration
- **THEN** the p95 of the 10 measurements is < 30 seconds
- **AND** the CI gate fails the run if p95 ≥ 30 seconds

#### Scenario: Replay cache hit on identical input

- **GIVEN** a brief was synthesized for AAPL with methodology="3-pillar" and feature_bundle X (`feature_hash=H`)
- **WHEN** a second `BriefService.refresh("AAPL", "3-pillar")` is invoked with the same feature bundle (no facts ingested in between)
- **THEN** O1's `ObservabilityClient.complete()` returns the cached LLM output (no upstream LLM call)
- **AND** the cost ledger does NOT increment a new `api_cost_events` row for that call (it references the prior call)
- **AND** the new brief is persisted with `version+1` (immutability per R1 D5) but `audit_trail.llm_call_id` references the cached call

### Requirement: Citation chain reproducibility (NFR-O8 caveat)

The system SHALL guarantee that, given a brief and the original facts referenced, regenerating the brief with the same `(model_id, methodology, feature_bundle)` yields the **identical citation set** (same fact_ids referenced) modulo LLM stochasticity in PROSE wording. The replay_cache via O1 covers determinism in tests. The brief PROSE may vary across non-cached regenerations; the **citation chain** (set of `[fact:<uuid>]` markers) is deterministic-by-construction because the input bundle constrains the LLM's available citations. CI snapshot tests SHALL detect drift in the citation set when input is unchanged.

#### Scenario: Re-synthesizing the same brief in tests yields identical body via replay_cache

- **GIVEN** a brief was synthesized for AAPL with methodology="canslim" and recorded by replay_cache
- **WHEN** the test re-runs `Synthesizer.synthesize()` with the same `(symbol, methodology, feature_hash)` input
- **THEN** the returned `body_markdown` is byte-identical to the recorded output
- **AND** the citation set extracted via the regex matches exactly

#### Scenario: Citation set is stable across non-cached regenerations

- **GIVEN** two production runs of `BriefService.refresh()` for AAPL with the same feature bundle but `replay_cache` disabled (e.g., cache eviction)
- **WHEN** both runs complete successfully
- **THEN** the set of fact_ids cited in each brief's body is IDENTICAL
- **AND** the prose wording MAY differ (LLM stochasticity, documented caveat)

### Requirement: Failure modes degrade gracefully (LLM down, budget exceeded, missing data)

The system SHALL handle synthesis failures per the matrix in design D10. LLM provider downtime SHALL return the most recent immutable brief from `latest_brief()` with `stale=true`, NOT raise to the user. Budget exhaustion SHALL return 429 RFC 7807 with `type="urn:iguanatrader:error:budget-exceeded"` and `retry_after`. Missing tier-A required features SHALL produce a brief with `partial=true` and explicit `missing_features` list rather than failing the synthesis.

#### Scenario: LLM 5xx returns stale brief

- **GIVEN** the most recent immutable brief for AAPL is version 3
- **AND** the LLM provider returns 503 for the next refresh attempt
- **WHEN** the user invokes `POST /research/briefs/AAPL/refresh`
- **THEN** the response is `200 OK` with the version-3 brief body
- **AND** the response includes `stale=true` and `last_attempt_failure="LLM provider unavailable"`
- **AND** structlog event `research.brief.refresh.failed.llm_unavailable` is emitted
- **AND** the frontend renders a `Toast` warning per j3.md §3 Step 2 edge case

#### Scenario: Monthly budget exhausted returns 429

- **GIVEN** the tenant's monthly LLM cost has reached the configured budget
- **WHEN** `POST /research/briefs/AAPL/refresh` is invoked
- **THEN** the response is `429 Too Many Requests`
- **AND** the response body has `type="urn:iguanatrader:error:budget-exceeded"`, `retry_after` set to the budget window reset time
- **AND** the frontend renders the tooltip "Today's LLM budget exhausted — refresh queued for next budget window" per j3.md §3 Step 2 edge case

#### Scenario: Missing tier-A feature produces partial brief, not failure

- **GIVEN** AAPL has no `eps_diluted` fact in `research_facts` (EDGAR not yet ingested)
- **WHEN** `BriefService.refresh("AAPL", "canslim")` is invoked
- **THEN** the brief is synthesized successfully with `partial=true`
- **AND** `MethodologyResult.missing_features` includes `"eps_diluted"`
- **AND** the brief body includes the explicit copy "C pillar: data unavailable at this knowledge-time" per j3.md §6 edge case
