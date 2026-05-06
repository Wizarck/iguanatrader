# Retrospective: orchestration-scheduler-routines (O2)

- **Archived**: 2026-05-06
- **PR**: [#93](https://github.com/Wizarck/iguanatrader/pull/93)
- **Archive path**: `openspec/changes/archive/2026-05-06-orchestration-scheduler-routines/`
- **Lines shipped**: ~700 LoC (6 src + 2 test files + migration).

## What worked

- **Sixth slice in a row using the "Protocol + InTreeFake + DeferredProductionInstall" pattern**. SchedulerProtocol + InMemoryScheduler fake — production APScheduler swap is one drop-in. The pattern is now canonical for any slice touching a heavy external dep.
- **Pure-data alert-rule table** (`CANONICAL_RULES`) — adding a 14th rule is one tuple entry + one unit test. Payload predicates (e.g. `_insider_buy_pct_ge_10`) are simple module-level functions; if a rule's payload predicate fails it auto-downgrades to TIER_3.
- **Idempotency via `uq_routine_runs_routine_name_scheduled_at_tenant_id`** — duplicate scheduler triggers fail-fast at the DB → caught + status='skipped_duplicate'. No special locking.
- **Routine pipeline as plain async data-flow** (no LangGraph) — classify → persist → digest. The 4 routine names are just strings; per-routine logic is a deterministic title + template pair. Future LLM synthesis is a one-line swap of `_DETERMINISTIC_TEMPLATE` lookup with an `LLMClient.complete()` call.

## What didn't

- **Sixth migration-slot collision in a row**. tasks.md called for `0007`; ended up at `0011` because R1/R2/R5/R3/T2/O2 all collided. ai-playbook v0.11 slot reservation in `docs/openspec-slice.md` is OVERDUE.
- **No actual cron firing in tests** — the scheduler fake doesn't emulate cron schedules; tests drive the service directly. A future deployment-foundation integration test should verify APScheduler + freezegun cron-firing semantics.
- **No SSE `/stream/alerts` endpoint** — design called for it; cut for scope. W2 frontend slice is the natural home.
- **No tier-1 channel emission** — service classifies + persists, but the actual Telegram/Hermes emission is P1's surface. T4 wires the bus subscription.
- **No reportlab PDF for weekly_review** — emits markdown digest only. Follow-up `weekly-review-pdf` slice needed for FR44.

## Lessons

- **Protocol + InTreeFake is now THE Wave-3 default**. Six slices: R5 LLMClient, T2 IBClient, R3 ScrapeTier-2/3/4, R3 OpenInsider/Finviz/Bars (deferred), T2 fake-only-no-real-broker, O2 SchedulerProtocol. Promote to ai-playbook v0.11 as a named pattern.
- **Static rule tables > dynamic config files** for v1. The CANONICAL_RULES tuple is auditable + diffable in PR review; a YAML file would shift the audit boundary and add a parser.

## Carry-forward to next change

- **`deployment-foundation` slice** (most-overdue, mentioned by 6+ retros): APScheduler + ib_async + anthropic SDK + Playwright + Camoufox + 2Captcha + reportlab installs + Helm chart unifying all components.
- **`weekly-review-pdf` slice**: reportlab PDF generator for FR44.
- **`trading-routes-and-daemon` (T4)**: wires every Wave-3 service end-to-end (StrategyManager → Risk → Approval → IBKRAdapter → Fill → equity update). The keystone slice that turns the bot into a working agent.
- **ai-playbook v0.11 deliverables** — SEVEN slices' worth of carry-forward retro lessons:
  - Migration slot reservation in `docs/openspec-slice.md` (SIX collisions now).
  - "Protocol + InTreeFake + DeferredProductionInstall" named pattern (SIX consecutive).
  - "Cross-slice additive-field-extension" named pattern (FOUR slices).
  - openspec-apply preflight: re-grep cited identifiers from prior slices' archived specs.
  - Lock-workflow first-run smoke (R4 retro, still pending).
  - Class-level cache test reset pattern in AGENTS.md (R2 retro, still pending).
  - "External-SDK isolation via Protocol" named pattern (T2 retro, still pending).
