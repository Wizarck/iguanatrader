# Retrospective: dashboard-svelte-skeleton (slice W1)

- **Archived**: 2026-05-06
- **Archive path**: openspec/changes/archive/2026-05-06-dashboard-svelte-skeleton/
- **Schema**: spec-driven
- **PR**: #72 (squash-merged 2026-05-06; CI 15/15 green incl. AI-self-review; required force-push three times across the merge cycle)

## What worked

- **Dynamic Sidebar via `import.meta.glob`.** Adding a new `(app)/<name>/+page.svelte` file appears in the sidebar automatically (with a hard reload — gotcha #70). No central registry to update; Vite's compile-time macro handles it.
- **Defensive `lib/types/problem.ts` fallback.** While `packages/shared-types/src/index.ts` is a placeholder until the typegen bot fires, W1 ships a structurally-compatible `Problem` type so `+error.svelte` builds today. When the bot lands real types the fallback becomes a no-op alias (gotcha #71).
- **Tailwind 4.x via `@tailwindcss/vite`** (no `tailwind.config.ts`, no PostCSS) — design tokens cascade from CSS custom properties under `:root[data-theme='dark']`. Documented as gotcha #72 because it surprises Tailwind 3.x devs.
- **`useSSE` composable with canonical `[3, 6, 12, 24, 48]` backoff.** Mirrors slice 2's HeartbeatMixin but runs client-side, fires only on `EventSource` `error` (gotcha #73 documents the orthogonality).
- **Lighthouse CI a11y ≥ 95.** Bumped from baseline 90 because the stub-page surface is small and clean — easy to keep above 95 even as the dashboard grows.

## What didn't

- **Three force-pushes during the merge cycle** (W1 → P1 land → re-rebase → O1 land → re-rebase → merge). Each re-rebase hit the same conflict pattern on `docs/gotchas.md` because every Wave-2 sibling appended new entries. Mechanical fix but tedious — happens because W1 is the last to merge and accumulates conflicts from every prior sibling.
- **Backend CI checks initially skipped on path-filter** (W1 only touches `apps/web/` + `docs/` + `packages/`). Required-status-checks (the 7 named contexts) were "expected" — not pass, not pending, blocking merge. The first force-push reset the path filters and triggered backend jobs. Could be avoided by ensuring the slice-level changes touch a backend path or by explicitly registering W1 changes against the backend pipeline.
- **Light-mode CSS variants deferred.** `theme` store + `data-theme` attribute + system-pref reader land, but the OKLCH inverse for every token is non-trivial — punted to a follow-up slice (gotcha #74). Users who set system pref to "light" still see dark colors today.

## Lessons

- **Last-to-merge slice pays the rebase tax.** When 4-5 sibling slices share `docs/gotchas.md`, `apps/api/README.md`, etc., the last merger rebases over every prior merge. Future Wave 2-style waves should sequence the smallest / simplest slice last (W1 was good — frontend-only with no backend conflicts) but accept the README/gotchas conflict cost.
- **Path-filter behaviour for required status checks is non-obvious.** When a PR touches only frontend, backend jobs skip on path filter; required checks remain "expected" and block merge. The merge CI pipeline could either: (a) always run all required jobs (simplest), (b) explicitly mark "skipped on path filter" as a pass equivalent. Option (a) is what we landed in by accident — a force-push triggers all jobs.
- **Defensive type fallbacks in package boundaries are cheap.** `lib/types/problem.ts` matches the slice-5 Pydantic schema field-for-field; ~30 lines of TypeScript. Cost is trivial compared to the unblock value (W1 doesn't have to wait for the typegen bot to land its first real types).

## Carry-forward to next change

- **Light-mode CSS variants** — non-MVP follow-up slice. The `theme.svelte.ts` store has a TODO inline marker.
- **CI path-filter behaviour** — release-management.md should document the "force-push triggers all jobs" workaround OR the workflows should switch to required-status-checks-skipped-via-path-filter-counts-as-pass model.
- **Docs/gotchas.md anchor architecture** — consider splitting into per-slice files or a top-level ToC to reduce three-way conflicts on the next wave.
