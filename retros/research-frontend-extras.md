# Retrospective: research-frontend-extras

> **Forward-authored**. Scope-reduced ship of the original research-frontend-components spec — delivers JTBD-4 visibility win (clickable citation chips) without the full 5-component / Playwright / Storybook surface. Remaining components (FactTimeline + AuditTrailViewer) + audit-trail nested route + deps (marked + DOMPurify) + Playwright + Storybook + Lighthouse threshold extension are deferred to a future `research-frontend-extras-2` slice.

- **PR**: [#113](https://github.com/Wizarck/iguanatrader/pull/113) (merged 2026-05-10, squash `05fd1bd`).
- **Archive path**: `openspec/changes/archive/2026-05-10-research-frontend-extras/`
- **Lines shipped**: 492 insertions / 40 deletions across 8 files (~330 Svelte/TS + ~80 page rewrite + ~80 openspec/retro). CI 14/14 verde al primer push (mypy + Lighthouse a11y both green).

## What worked

- Hand-rolled `parseCitations` regex-splitter avoids needing marked + DOMPurify deps — license-boundary CI risk averted entirely.
- 3 components shipped in a single coherent surface (MethodologyBadge + CitationLink + BriefHeader) instead of a 5-component megaslice.
- Existing R5 backend routes (`/api/v1/research/briefs/{symbol}` + `/facts/{symbol}`) consumed without modification — zero backend changes.
- CI 14/14 verde al primer push (svelte-check + Lighthouse + everything else); no fix iterations needed.
- `$derived.by` for the fact-id lookup map keeps the component reactive when facts arrive later without leaking imperative state.

## What didn't

- Deferred FactTimeline + AuditTrailViewer means brief body is still rendered as plain text inside the brief-body `<div>` (no markdown→HTML, no link/list/heading rendering). Hyper-minimal scope tradeoff to ship JTBD-4 (clickable citations) without the full markdown pipeline.
- Initial each-block syntax used `data.facts as FactRow[] as fact (...)` (invalid Svelte syntax — cast inside iterable position). Fix: `$derived` the cast at script level, then iterate the typed array. Pre-flag for future Svelte+TypeScript work: do casts in `<script>`, not in `{#each}` headers.

## Carry-forward

- **`research-frontend-extras-2` slice** (next operator session):
  - `FactTimeline.svelte` (compact + full + as-of modes; bitemporal rendering).
  - `AuditTrailViewer.svelte` (accordion + deep-link).
  - `/research/[symbol]/audit-trail/[brief_version]/+page.{svelte,server.ts}` nested route.
  - marked + DOMPurify deps (with license-boundary CI clearance).
  - Full markdown→HTML rendering replacing the current `<pre>` block.
  - Playwright e2e specs (research-brief-detail + research-audit-trail).
  - Storybook stories per components.md §4 verbatim.
  - Lighthouse a11y threshold extension to research routes.
