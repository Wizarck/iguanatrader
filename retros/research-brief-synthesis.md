# Retrospective: research-brief-synthesis (R5)

- **Archived**: 2026-05-06
- **PR**: [#86](https://github.com/Wizarck/iguanatrader/pull/86)
- **Squash SHA**: see PR #86 mergeCommit
- **Archive path**: `openspec/changes/archive/2026-05-06-research-brief-synthesis/`
- **Schema**: spec-driven
- **Tasks**: 12 groups, ~123 sub-tasks. Backend 100% shipped (groups 1-8, 11, 12). Frontend partial (group 9 minimal page only; groups 10/11 deferred — 5 design-system components + Playwright e2e + Lighthouse a11y land in a follow-up `research-frontend-components` slice).
- **Lines shipped**: ~3000 LoC (~2400 backend + ~200 frontend + ~400 tests + 5 prompt templates).

## What worked

- **Pragmatic scope reduction up-front + 8 deviations documented in PR body**. R5 is the biggest Wave-3 slice by far — explicitly carving out the frontend components into a follow-up at the start (instead of mid-slice) kept the implementation focused on the load-bearing backend pipeline. CodeRabbit had no blocking comments on the deviations.
- **Sync-vs-async honest re-evaluation**. R4 + R2 retros flagged the systemic "tasks.md authored before prior slice's archive" pattern. For R5 I re-checked R1's actual `SourcePort` (sync) + repository (async) + DTO surfaces BEFORE writing code. Saved the rework cycle.
- **5 methodologies in one read pass**. Each methodology is ~80 LoC of pure scoring + a docstring with research-paper citation. Sharing the `clip_unit_interval` / `normalise_growth` helpers in `base.py` collapsed duplication. mypy --strict caught zero issues across the 5 modules; tests parametrised across `METHODOLOGY_REGISTRY` covered all five with one test body.
- **`Synthesizer._compute_replay_key` + `FakeLLMClient.register(key, body)` pattern** made the synthesizer pipeline testable without an LLM stub framework. Tests inject canned outputs keyed deterministically; the same pattern transfers to real production replay-cache testing once the Anthropic client lands.
- **CitationResolver as a static helper + instance method**. The static `parse_markers` / `validate_against_bundle` pair is the synthesizer's pre-persist gate (no DB calls); the instance `resolve` method does the DB lookup for route handlers. Same regex, same UUID parsing — clean separation between "parse" and "resolve".
- **Tier-B safety encoded in the API shape**. `TierBFeatureProvider.fetch(symbol, since=None)` returns all-None bundle. Backtest callers accidentally passing `since=None` get None across the board (no future-knowledge leak); production callers pass an explicit `since` (now or recorded_from constraint). Type signature alone enforces the contract; no runtime assertion needed.
- **Repository extensions kept additive**. R1's `insert_brief` was a stub; R5 fills it with a method that is keyword-only + non-breaking. New methods (`latest_fact_by_kinds`, `facts_by_ids`, `facts_for_symbol`, `insert_audit_trail_entry`, `audit_trail_for_brief`) are all new surface — zero R1 method signatures changed.
- **Local mypy + ruff + black before push** kept CI to a single round (lesson from R4 retro). 12 task groups + ~3000 LoC and the only CI red was the non-blocking CodeRabbit fallback (same pattern as R2 + R4).

## What didn't

- **R5's tasks.md called for slot `0008`** for `0008_research_audit.py`. R2 took `0008` (`0008_research_dedupe_index`). I claimed `0009_research_audit_trail` for R5 + documented in commit body + retro. **Third occurrence of the cross-slice slot collision pattern** (R1→0003 was a deviation from tasks.md `0002`; R2→0008 was a deviation from tasks.md `0004`; R5→0009 is a deviation from tasks.md `0008`). The fix is overdue: ai-playbook v0.11 should reserve slots in `docs/openspec-slice.md` per row.
- **`ObservabilityClient.complete()` is fictional in O1**. R5 design.md said the synthesizer "invokes LLM via O1's `ObservabilityClient.complete(...)`". O1 actually ships `route_llm()` + `cost_meter` decorator + `replay_cache` context manager + `check_budget()` — composable primitives, not a single facade class. R5 ended up with a `LLMClient` Protocol + `FakeLLMClient` implementation; the production `AnthropicLLMClient` would compose `route_llm` + `@cost_meter` + `replay_cache(scenario)` around an Anthropic SDK call.
- **No production LLM client shipped**. Anthropic SDK is a security-review item: API key handling, prompt-caching activation, version pinning, secret-rotation. I did not add the SDK dep in this slice; instead the synthesizer + service + routes + CLI all wire the `FakeLLMClient`. End-to-end production capability is **gated on a deployment-foundation slice that adds the SDK** with proper pinning + secret handling.
- **No real "show your work" frontend yet**. The `/research/[symbol]/+page.svelte` renders the brief markdown as raw `<pre>` (no DOMPurify, no marked, no `[fact:<uuid>]` → `CitationLink` substitution). A user can READ the synthesised brief but cannot click a citation to see the source fact. JTBD-4 ("anti-hallucination") is structurally enforced (the synthesizer rejects invented UUIDs) but not visually delivered until the components slice.
- **`body_markdown` field naming confusion**. R5 design.md treated `body_markdown` as a new column on `BriefResponse`; R1's existing `thesis_text` IS the brief body. I documented the additive `body_markdown` field on BriefResponse mirroring `thesis_text` for forward-compat, but a future cleanup could drop one of the two names. Will land naturally in the components slice when the frontend renderer hardens.
- **Tier-A feature provider only reads SEC EDGAR XBRL + FRED kinds**. R2's adapters write the facts; R3 (Tier-B/C) writes more; R5's `_FACT_KIND_BY_FEATURE` registry only mapped a handful (`eps_diluted`, `revenue`, `cpi_yoy`, `unemployment_rate`, `fed_funds_rate`). Real ingest will need the full mapping. Not blocking — scheduler integration in O2 is when this surfaces.
- **No SSE publisher loop**. The endpoint at `/api/v1/stream/research` accepts connections + heartbeats every 15s; the `event` queue is allocated but never fed. O2's cron scheduler (which has access to the bus subscriber it wires up) is the natural home for the publisher. R5's frontend doesn't depend on SSE for MVP — Refresh button is a synchronous POST.

## Lessons

- **Migration slot pre-allocation is a v0.11 ai-playbook deliverable, not a future-nice-to-have**. Three slot collisions in three slices in the same wave is enough evidence. The `docs/openspec-slice.md` schema needs a `migration_slot` column reserved per row + a CI check that warns when a slice's `0NNN_*.py` doesn't match its reserved slot.
- **When a slice cites a class/function from a prior archived slice, re-grep the archived spec at apply time**. R5 design.md cited `ObservabilityClient.complete()` which never existed; R2 design.md cited `exponential_backoff` which is named `backoff_seconds`; R4 + R2 cited HeartbeatMixin / async SourcePort which is sync. The pattern is systemic: design.md is authored before the prior slice's archive resolves the names. **Future openspec-apply preflight: grep the cited identifier in current main; if absent, surface the deviation in the apply plan before code-write.**
- **LLM client abstraction (Protocol + Fake + Production) is the right Wave-3 shape**. R5's `LLMClient` Protocol with `FakeLLMClient` test-double + a deferred `AnthropicLLMClient` keeps the synthesis pipeline testable today without committing to the SDK security-review scope. Future slices that add LLM features (R6 Hindsight, future routine-summary jobs) can share the same Protocol.
- **Frontend in a synthesis slice is an anti-pattern when the design system is incomplete**. Shipping `/research/[symbol]` without the locked design tokens / `CitationLink` / `BriefHeader` / `MethodologyBadge` means the page exists but doesn't deliver the JTBD. Cleaner: ship the **API contract** first (R5), then ship the **rendering pipeline** (`research-frontend-components`) once the design system has all primitives. Avoids half-shipped UI surfaces.
- **Pure-function methodology framework is the right foundation for v2 extensibility**. Even if a 6th methodology (e.g. piotroski_score, GARP, ESG-tilted) demands YAML-driven config in the future, the current 5 are research-paper-grade fidelity. The `METHODOLOGY_REGISTRY` dispatch makes adding a 6th a one-liner + new module.

## Carry-forward to next change

- **`research-frontend-components` slice** (next obvious): 5 Svelte components per `docs/ux/components.md §4` (`BriefHeader` / `FactTimeline` / `CitationLink` / `AuditTrailViewer` / `MethodologyBadge`) + `/research/[symbol]/audit-trail/[brief_version]` nested route + `lib/research/render-brief.ts` (DOMPurify + marked + `[fact:<uuid>]` → mounted `CitationLink` substitution) + 2 Playwright e2e specs + visual baselines + Lighthouse a11y gate. Adds `marked@^14` + `dompurify@^3` deps.
- **`deployment-foundation` slice** (post-Wave-3): production `AnthropicLLMClient` wiring (`@cost_meter("anthropic", "claude-3-5-sonnet")` decorating `messages.create()` calls) + `ANTHROPIC_API_KEY` SOPS handling + Helm chart for api + sidecar + litestream + frontend.
- **O2 scheduler `research-brief.refresh` cron job** + SSE publisher loop subscribing to `ResearchFactIngested` + emitting on `/api/v1/stream/research`.
- **R6 `hindsight-bridge`** subscribes to `ResearchBriefSynthesized` events (R1 declared the event, R5 emits it on bus when one is provided) → triggers Hindsight retain hook.
- **T4 `trade_proposals.research_brief_id` FK** consumes `BriefResponse.id` (R5 wrote the schema; T4 wires the FK at proposal generation time).
- **ai-playbook v0.11 deliverables** (third retro in a row to flag this):
  - Migration slot pre-allocation in `docs/openspec-slice.md`.
  - openspec-apply preflight: re-grep cited identifiers from prior slices' archived specs.
  - Lock-workflow first-run smoke (R4 retro carry-forward, still pending).
  - Class-level cache test reset pattern in AGENTS.md (R2 retro carry-forward).
- **Tier-B feature kind registry** (`_FACT_KIND_BY_FEATURE` in `tier_b.py`) is half-empty; expanding it as R3's adapters land is straightforward (add the OpenBB sidecar + Finnhub fact_kinds).
- **`body_markdown` vs `thesis_text` naming**: pick one in the components slice. Either rename `thesis_text` to `body_markdown` in a migration (R5's `thesis_text` was R1's terminology) or drop `body_markdown` from the DTO (the field is currently a redundant alias).
