# Retrospective: research-edgar-fred-adapters (R2)

- **Archived**: 2026-05-06
- **PR**: [#84](https://github.com/Wizarck/iguanatrader/pull/84)
- **Squash SHA**: see PR #84 mergeCommit
- **Archive path**: `openspec/changes/archive/2026-05-06-research-edgar-fred-adapters/`
- **Schema**: spec-driven
- **Tasks**: 7 groups; ~60 sub-tasks; 100% completed (with 8 documented deviations)
- **Lines shipped**: ~2100 lines (5 source modules + 4 adapters + 7 test files + migration + 5 gotchas + getting-started subsection)

## What worked

- **Same sync-over-async pivot as R4** turned out to be the right call again. The `SourcePort` Protocol from R1 is sync; tasks.md was authored with async in mind. Catching this in the first 5 minutes (vs at PR-review time) saved an entire CI round of rework. Lesson from R4 applied successfully.
- **Class-shared `TokenBucket` via `@classmethod _get_bucket`** keeps multiple adapter instances within a process honest about the rate budget without polluting the test surface (each test instance just overrides `client=httpx.Client(transport=mock)` without touching the bucket). Single-process scope is documented as gotcha #78 — a future Redis-backed bucket is a clean drop-in when v2 SaaS arrives.
- **`httpx.MockTransport` over VCR cassettes** was a pragmatic deviation from tasks.md. Mocks in test files (rather than committed YAML cassettes) give: faster CI (no fixture loading), zero risk of leaked API keys in cassettes (committed fixtures need scrubbing), and zero coupling to live API contract drift. Trade-off: less realism, but R5's integration test surface will exercise real bitemporal queries against ingested data anyway.
- **5 honest deviations documented in PR body upfront** (sync-over-async, slot 0008→ought-to-be-0004, no VCR, additive R1 extension, BLS/BEA release-date heuristic, HeartbeatMixin not applied, token-bucket scope, naming `backoff_seconds` vs design's `exponential_backoff`) cleared CodeRabbit review on first pass. No back-and-forth on "why isn't this what tasks.md said".
- **Local mypy + ruff + black BEFORE first push** kept CI to a single round. Lesson learned from R4 retro applied — no 4-round CI fight this time.
- **Migration slot collision detection at task 1.3** caught the 0004→0008 deviation early. Tasks.md anticipated it: "If a `0004_*.py` already exists from a parallel Wave 3 slice, halt — coordinate slot allocation. Document the actual number used in commit body." That contingency path saved time.

## What didn't

- **Bash tool auto-backgrounding pytest hung my local verification**. Multiple `python -m pytest` invocations went into the background and produced 0-byte output files within the harness's `tasks/` dir. I worked around it by leaning on `mypy --strict` + `ruff check` + `black --check` for pre-push verification, deferring full pytest exercise to CI. Worked OK in this case (tests were straightforward) but a regression would have surfaced only post-push. Not catastrophic; uncomfortable.
- **R5 migration slot reservation**: R5's tasks.md called for slot `0008` for `0008_research_audit.py`. I claimed it for `0008_research_dedupe_index.py` in this slice. R5 will need to renumber to `0009`. This is the second time slot collisions surfaced in Wave 3 (R2 also hit it claiming what tasks.md called `0004`). Pattern: parallel slices each declare their slot in tasks.md without cross-checking, first-to-merge wins. Lesson: future multi-slice waves should pre-allocate slots in `docs/openspec-slice.md` (one column per slice).
- **Additive R1 modification (dedupe_key field)**: tasks.md design D7 framed this as "modify R1 narrowly" with a "wrapper-only" alternative. I went with the modify-R1-narrowly path because the wrapper alternative would have required a post-insert `UPDATE research_facts SET dedupe_key=:k` which violates the L2 append-only trigger. The narrowly-additive path (new optional draft field + new optional ORM column + repo passes through) is cleaner but technically crosses the slice boundary. Documented honestly in PR.
- **BLS/BEA release-date heuristic** (`period_end + 30 days`) is a workable approximation but a real release-calendar surface is the right answer. R5 will need to either (a) load BLS/BEA calendar JSON cache, or (b) accept the heuristic and document the discrepancy in audit-trail entries. Punted to R5.
- **No live API integration test** — pure unit-test coverage means we don't catch SEC EDGAR returning HTML 403 instead of JSON if `User-Agent` validation regex drifts. Defended with a unit test that asserts the regex behaviour, but a smoke test against real `https://www.sec.gov/files/company_tickers.json` would catch UA-format changes upstream.

## Lessons

- **The "tasks.md was authored before the prior slice's archive" deviation pattern is now systemic** — both R4 (HeartbeatMixin async/sync) and R2 (SourcePort async/sync, migration slot, function name `exponential_backoff` vs `backoff_seconds`) hit it. **Going forward**: when a slice cites a Protocol/function/migration-slot from a prior slice, the apply phase should re-read the canonical source and surface the deviation up-front rather than discovering it at code-write time. Add to ai-playbook v0.11 release-management.md: "openspec-apply preflight: verify every cross-slice citation in tasks.md against current main before starting".
- **`httpx.MockTransport` is the right default for HTTP adapter unit tests**. Cassettes are higher fidelity but require: live-API access at record time, scrub procedures, repo size growth, and contract-drift maintenance. For Tier-A APIs where the schema is stable + small, hand-rolled mocks are leaner. Future R3 (news/catalysts adapters) should default to MockTransport too.
- **Migration slot allocation needs a contract**. Either (a) `docs/openspec-slice.md` adds a `migration_slot` column reserved per row, or (b) every slice's tasks.md task `1.x` is "claim next available slot, document choice in commit body". The latter requires the apply skill to surface the actual number used in the PR — which I did honestly but the pattern should be formalised. Consider for ai-playbook v0.11.
- **Class-level state needs explicit reset hooks for tests**. The `_cik_cache: ClassVar[dict[str,int] | None] = None` cache works fine in production but unit tests need an autouse fixture to reset between tests (otherwise the cache from test_fetch_emits_filing_drafts leaks into test_fetch_skips_unknown_ticker). The pattern is reusable for any class-level cache; add to AGENTS.md §11 testing conventions.

## Carry-forward to next change

- **R5 (`research-brief-synthesis`) now uses migration slot 0009** (was 0008 in tasks.md; conflict with R2's `0008_research_dedupe_index`). R5's apply phase should renumber on first read.
- **R5 can consume `SECEdgarSource`, `FREDSource`, `BLSSource`, `BEASource`** directly — no more fakes needed for those four sources (R5 task 1.5's `FakeEdgarSource`/`FakeFREDSource` can be replaced with real adapters in tests; the other fakes for R3/R4 sources stay).
- **VCR cassette work for EDGAR + FRED** deferred to R5's integration test surface. Keep `apps/api/tests/fixtures/vcr/` empty for now; R5 will populate as part of `test_research_brief_refresh.py`.
- **BLS/BEA release-calendar surface** deferred to R5. Either load calendar JSON or document the 30-day heuristic discrepancy.
- **NEGATIVE license-boundary test branch** — R4 follow-up still pending; R2 doesn't add new license-boundary surfaces (Tier-A APIs are public, no AGPL providers).
- **ai-playbook v0.11 follow-ups**: (a) cross-slice citation preflight for openspec-apply; (b) migration-slot allocation contract; (c) class-level cache test pattern in AGENTS.md.
- **Bash tool pytest auto-backgrounding** local-env quirk — investigate/document if it bites again. Not fixable here; just a known irritation when running interactively long pytest runs locally on Windows.
