# Retrospective: research-frontend-settings-page

> Scope-reduced rename of original `research-frontend-components` proposal. Ships only the Settings page (closes R6 hindsight-integration carry-forward); deferred 5 components + audit-trail route + Playwright + Storybook + Lighthouse threshold extension to a future `research-frontend-extras` slice.

- **PR**: TBD
- **Archive path**: `openspec/changes/archive/<archive-date>-research-frontend-settings-page/`
- **Lines shipped**: ~150 LoC (~120 .svelte + ~25 .server.ts + retro/openspec).

## What worked

- _(fill on archive — pre-flag candidates: scope reduction shipped quickly + addressed the highest-value R6 carry-forward (operator no longer forced into CLI for hindsight toggle); existing `+page.svelte` route layout from W1 absorbed the new body cleanly; CSS tokens (`var(--accent)`, `var(--mute)`, etc.) inherited from W1 design system without new design.)_

## What didn't

- _(fill on archive — pre-flag candidates: original `research-frontend-components` proposal was 5 components + audit-trail route + e2e + Storybook ≈ 8-10h scope; deferring 5 components means JTBD-4 "show your work — anti-hallucination" remains visually-incomplete (citation chips still render as raw `[fact:<uuid>]` text). Acceptable for v1.0 backlog closure but visible UX gap.)_

## Carry-forward

- **`research-frontend-extras` slice**: BriefHeader + FactTimeline + CitationLink + AuditTrailViewer + MethodologyBadge + brief renderer pipeline (marked + DOMPurify) + audit-trail nested route + Playwright e2e + Storybook stories + Lighthouse threshold extension. Original spec preserved in this archive.
- **`research-frontend-extras` priority**: medium-low. JTBD-4 backend invariants are enforced (synthesizer rejects invented UUIDs; structured citations); the visual delivery is a nice-to-have for the operator, not a v1 critical-path item.
