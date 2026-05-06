# Retrospective: observability-cost-meter (slice O1)

- **Archived**: 2026-05-06
- **Archive path**: openspec/changes/archive/2026-05-06-observability-cost-meter/
- **Schema**: spec-driven
- **PR**: #73 (squash-merged 2026-05-06; CI 14/14 green incl. AI-self-review)

## What worked

- **`@cost_meter` decorator + integration test stack-introspection.** The decorator persists `ApiCostEvent` automatically when `tenant_id_var` is set + a session is bound. The integration test (`test_cost_meter.py`) walks `inspect.stack()` to flag bare SDK calls — a contract-level catch that doesn't need a static lint rule. Documented as gotcha #60.
- **Carry-forward of slice-5 retro items into O1.** Picks (a)/(b)/(e)/(f) — tenant_listener fix, prod cookie env-guard, `--cov-fail-under=80`, Windows poetry doc — landed cleanly because they're all "boundary hardening" small wins. Items (c)/(d)/L2-marker punted to slice O2 per design D9 (gotcha #63 documents the intent).
- **`route_llm` model-tier router with explicit budget gates (WARN_80 → BLOCK_100).** WARN_80 downgrades to Haiku, BLOCK_100 raises `BudgetExceededError`. The function emits `observability.llm.route_chosen` for downstream dashboards.
- **Process-local Perplexity throttle.** `collections.deque` + `asyncio.Lock` for the 60-second window. Documented as MVP-only single-process (gotcha #62) with a Redis-backed v2-SaaS upgrade path.

## What didn't

- **Migration revision normalization had to be re-applied at rebase.** The earlier "0007 → 0007_observability_tables" fix commit got dropped during `git rebase --continue` (alembic recognised the patch as already-upstream and skipped it), so the file reverted to `revision: "0007"`. Re-applied during the conflict-resolution step. Lesson: when normalising revision strings, do it earlier in the chain (before any other commits depend on it).
- **README.md three-way conflict at every rebase.** R1's "Research bounded-context" + K1's "Risk context" + P1's "Bounded contexts" + O1's "Observability" all share the same anchor section. Mechanical resolution but error-prone — we ended up with the same `## Bounded contexts` heading appearing twice across slices for a moment.
- **D9 carry-forward picks intentionally narrow.** Picks (a)/(b)/(e)/(f) only; (c) ORM-SELECT lint and (d) Argon2 auto-rehash punted to slice O2 because they fit better with the scheduler entry-point lint surface. The deferral is intentional but creates a follow-up tracking burden — gotcha #63 carries the list forward.

## Lessons

- **Migration revision strings should be set verbose-and-final from the slice-prompt onward.** The convention `<NNNN>_<table_topic>` (e.g. `"0007_observability_tables"`) eliminates a renumbering tax across slices. Add to the slice-prompt template.
- **Carry-forward picks belong in the design.md "out of scope" section.** Slice O1 design D9 explicitly listed which items it picked + which it punted; this made the rebase-and-merge phase smooth and gives slice O2 a clear todo list.
- **Process-local rate-limits are fine for MVP if documented.** The Perplexity throttle is correct for `uvicorn --workers 1` (the documented MVP deployment) and explicitly broken for multi-worker (gotcha #62 + future ADR-019). Calling out the limitation prevents future-you debugging mysterious 429s.

## Carry-forward to next change (slice O2 likely)

- **(c) ORM-SELECT-in-`get_current_user` lint rule** — wire as a custom ruff plugin in `tools/lint/`. Same pattern as the planned scheduler-entry-point lazy-import rule.
- **(d) Argon2 auto-rehash on login when stored params drift** — auth-context concern; lives with whichever slice owns `routes/auth.py` next.
- **L2 marker schema discoverability** — release-management.md backlog (not a slice).
- **Multi-worker Redis-backed throttle** — v2 SaaS ADR-019; out of scope until v2.
