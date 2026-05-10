# Retrospective: research-frontend-extras

> **Forward-authored**. Scope-reduced ship of the original research-frontend-components spec — delivers JTBD-4 visibility win (clickable citation chips) without the full 5-component / Playwright / Storybook surface. Remaining components (FactTimeline + AuditTrailViewer) + audit-trail nested route + deps (marked + DOMPurify) + Playwright + Storybook + Lighthouse threshold extension are deferred to a future `research-frontend-extras-2` slice.

- **PR**: TBD
- **Archive path**: `openspec/changes/archive/<archive-date>-research-frontend-extras/`
- **Lines shipped**: ~450 LoC frontend (~330 Svelte/TS + ~80 page rewrite + ~40 retro/openspec).

## What worked

- _(fill on archive — pre-flag candidates: hand-rolled `parseCitations` regex-splitter avoids needing marked + DOMPurify deps (license-boundary CI risk averted); 3 components shipped in a single coherent surface (MethodologyBadge + CitationLink + BriefHeader); existing R5 backend routes (`/api/v1/research/briefs/{symbol}` + `/facts/{symbol}`) consumed without modification.)_

## What didn't

- _(fill on archive — pre-flag candidates: deferred FactTimeline + AuditTrailViewer means brief body is still rendered as `<pre>` (no markdown→HTML, no link/list/heading rendering). Hyper-minimal scope tradeoff to ship JTBD-4 (clickable citations) without the full markdown pipeline.)_

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
