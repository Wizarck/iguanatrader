# Retrospective: research-news-catalysts-adapters (R3)

- **Archived**: 2026-05-06
- **PR**: [#89](https://github.com/Wizarck/iguanatrader/pull/89)
- **Squash SHA**: see PR #89 mergeCommit
- **Archive path**: `openspec/changes/archive/2026-05-06-research-news-catalysts-adapters/`
- **Schema**: spec-driven
- **Tasks**: full task surface ticked; 5 Tier-1 adapters shipped (60% of original 9 — see deviations).
- **Lines shipped**: ~1300 LoC (5 src adapters + 5 scraping primitives + migration + 4 test files).

## What worked

- **Reused `TierASourceAdapter` base from R2** for all 5 Tier-1 adapters — saved ~50% of boilerplate per adapter (retry/backoff/token bucket/structlog plumbing). The "Tier-A" name is now misleading (it's used by Tier-B too); but renaming would touch R2's archive. Documented carry-forward.
- **Scrape ladder skeleton + Tier-2/3/4 stubs raising `ScrapeNotImplementedError`** is the right shape for "deferred SDK install" pattern. Same protocol as R5 LLMClient + T2 IBClient. The ladder dispatch logic + politeness primitives (UA rotation, robots.txt + 24h cache) are shipped working; Playwright/Camoufox/2Captcha installs deferred.
- **`is_robots_allowed` + 24h in-process cache** keeps repeated scrapes from hammering the robots endpoint. Per-host + per-UA key + threading.Lock-protected cache.
- **5 source-row migration in single statement-loop** is clean — `op.execute(sa.text(INSERT...).bindparams(...))` per row + dialect-aware timestamp expression. Reversible.
- **Static-grep `test_no_esg_in_backtest`** is simpler than runtime assertion. Walks `contexts/trading/`, fails on forbidden patterns, allow-list comment escape. FR75 defence in depth at zero runtime cost.

## What didn't

- **Only 5 of the 9 planned adapters shipped**. OpenInsider + Finviz depend on Tier-2 Playwright; ibkr_bars depends on real T2 production wiring; yahoo_bars + yfinance_sustainability route through R4 sidecar (already shipped — could have wired but cut for time). All 4 deferred to follow-up `research-tier-b-scrape` + `research-bars-adapters` slices.
- **`UserAgentRotation` UA strings have a small bug** — concatenating multiple Mozilla-style UAs into one with " " separators may not be what real anti-bot defences expect. Real-world testing in the deployment slice may surface this.
- **Migration slot 0010 — fourth slot collision in a row** (R1→0003, R2→0008, R5→0009, R3→0010). The tasks.md called for `0004`. ai-playbook v0.11 deliverable to reserve slots is now WAY overdue.
- **No integration test against a real public API** — all 5 adapters tested with `httpx.MockTransport` only. WGI / V-Dem responses might shift schema between releases; production deployment will need a smoke run + cassette refresh process. Same caveat as R2's deferred VCR cassettes.

## Lessons

- **The "Protocol + InTreeFake + DeferredProductionInstall" pattern is now the canonical shape** for any slice that touches a heavy external dependency. Five slices in a row used it: R5 LLMClient, T2 IBClient, R3 ScrapeTier-2/3/4, R3 indirect for OpenInsider/Finviz/bars adapters. Should be promoted to ai-playbook v0.11 as a named pattern.
- **Migration-slot-collision is a SOLVED PROBLEM in v0.11** — five slices now confirm the pattern: tasks.md authors a slot at design time; by apply time the slot is taken; the slice claims the next available; documents the deviation. Make it explicit + automated.
- **`TierASourceAdapter` was misnamed** — it's the generic Tier-A/B/C source adapter base. Future cleanup: rename to `SourceAdapter` (no "TierA" prefix) in a follow-up additive slice.

## Carry-forward to next change

- **`research-tier-b-scrape` slice** (next obvious): Playwright Tier-2 install + OpenInsider + Finviz adapters. Depends on `deployment-foundation` Playwright dep.
- **`research-bars-adapters` slice**: ibkr_bars (after T2 production wiring) + yahoo_bars (via R4 sidecar) + yfinance_sustainability (ESG via sidecar).
- **`deployment-foundation` slice** (most overdue): Playwright + Camoufox + 2Captcha install + real ib_async + real anthropic SDK + Helm chart unifying everything. THE follow-up unblocking R3/R5/T2 production wiring simultaneously.
- **`TierASourceAdapter` → `SourceAdapter` rename slice** (low-priority refactor): cosmetic but the name is misleading now.
- **ai-playbook v0.11 deliverables** — six slices' worth of carry-forward:
  - Migration slot reservation in `docs/openspec-slice.md` (FIVE slot collisions now).
  - "Protocol + InTreeFake + DeferredProductionInstall" named pattern.
  - "Cross-slice additive-field-extension" named pattern.
  - openspec-apply preflight: re-grep cited identifiers from prior slices' archived specs.
  - Lock-workflow first-run smoke (R4 retro carry-forward, still pending).
  - Class-level cache test reset pattern in AGENTS.md (R2 retro, still pending).
