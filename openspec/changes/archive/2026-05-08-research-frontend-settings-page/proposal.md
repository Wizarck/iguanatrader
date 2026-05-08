# Proposal: research-frontend-settings-page

> **Scope-reduced rename** of the original `research-frontend-components` proposal. The original spec (5 Svelte 5 components + audit-trail nested route + Playwright e2e + Storybook + Lighthouse a11y gate) is preserved for a future `research-frontend-extras` slice. THIS slice ships only the Settings page (closes the R6 hindsight-integration carry-forward Web UI gap) so the operator can toggle `hindsight_recall_enabled` without resorting to the CLI.

## Why

R6 hindsight-integration (PR #107, archived 2026-05-08) shipped:

- Backend Hindsight subsystem (Port + 3 adapters + bus-bridge retain handler)
- Settings GET/PUT route (`/api/v1/settings/feature-flags`)
- CLI `iguanatrader settings feature-flag get/set`
- BUT: the existing Settings page (`apps/web/src/routes/(app)/settings/+page.svelte`) is a 14-line stub rendering `<p>loading…</p>`. Operator must use the CLI to toggle — frictious + not visible in the dashboard.

This slice replaces the stub with a working toggle UI consuming the existing GET/PUT routes.

## What

### `apps/web/src/routes/(app)/settings/+page.svelte` (REWRITE)

- Replace 14-line stub with a Svelte 5 `+page.svelte` + `+page.server.ts` pair.
- `+page.server.ts` `load`: fetch `/api/v1/settings/feature-flags` with the auth cookie passthrough; return `{ flags: FeatureFlagsOut, error: string | null }`.
- `+page.svelte`: render a single labelled checkbox for `hindsight_recall_enabled` with the existing universal-states pattern from `docs/ux/components.md §0.2` (default / hover / focus / disabled / loading / error). On change → POST `/api/v1/settings/feature-flags` with the new value; surface 4xx/5xx via inline error banner.

The component intentionally stays presentational (no extracted `Toggle.svelte` — that's the v2 design-system slice).

### Out of scope (deferred to `research-frontend-extras`)

- 5 Svelte 5 research components (BriefHeader, FactTimeline, CitationLink, AuditTrailViewer, MethodologyBadge).
- Brief renderer pipeline (marked + DOMPurify + `[fact:<uuid>]` substitution).
- `/research/[symbol]/audit-trail/[brief_version]/` nested route.
- Refresh button SSE wiring.
- Storybook stories.
- Playwright e2e specs (`research-brief-detail.spec.ts`, `research-audit-trail.spec.ts`).
- Lighthouse a11y threshold extension to the new routes.

These remain valuable for Journey 3 UX completion + JTBD-4 visibility but are NOT on the critical path for closing the v1.0 backlog. A future operator session can scope + ship them as `research-frontend-extras` without further design work (the original proposal text is preserved in this slice's archive for reference).

## Acceptance criteria

1. `apps/web/src/routes/(app)/settings/+page.svelte` renders the `hindsight_recall_enabled` toggle (no loading-stub).
2. `+page.server.ts` calls `/api/v1/settings/feature-flags` (GET on load, PUT on change).
3. Loading state visible during async work (no flicker).
4. Error state visible if the PUT returns non-2xx.
5. Existing W1 layout/sidebar intact (no regression).
6. Lint (eslint + prettier if configured) passes.
7. Lighthouse a11y on `/settings` ≥ 95 (matches W1 threshold).

## Blast radius

ZERO backend changes. Frontend-only edit to one route. No new deps. No archive surface modification (the W1 + R6 routes are untouched).

## Estimated effort

~1.5h, ~120 LoC (~80 .svelte + ~30 .server.ts + ~20 retro/openspec).
