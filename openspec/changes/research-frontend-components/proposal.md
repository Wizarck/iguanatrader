## Why

Slice R5 (`research-brief-synthesis`, archived 2026-05-06) shipped the synthesis backend + 4 routes + minimal `/research/[symbol]` page rendering brief markdown as raw `<pre>`. **The user can read the brief but cannot click a citation, expand the audit trail, or visualise the fact timeline.** JTBD-4 ("show your work — anti-hallucination") is structurally enforced (synthesizer rejects invented UUIDs) but not visually delivered.

This slice ships the 5 design-system components per [docs/ux/components.md §4](../../../docs/ux/components.md#4-research-domain-components-journey-3) verbatim contracts + the audit-trail nested route + the brief markdown renderer with `[fact:<uuid>]` substitution + Playwright e2e tests + Lighthouse a11y gate. Pure additive frontend slice — zero backend changes.

## What Changes

- **5 Svelte 5 components** at `apps/web/src/lib/components/research/`:
  - `BriefHeader.svelte` (components.md §4.1) — symbol + version chip + methodology badge + refresh CTA + 3 states (default / refreshing / stale).
  - `FactTimeline.svelte` (§4.2) — 4 modes (compact / full / as-of / empty); axis = effective time; lanes = fact_kind.
  - `CitationLink.svelte` (§4.3) — inline `[fact:<uuid>]` substitution chip; 4 states (default / hover-tooltip / visited / broken-warning).
  - `AuditTrailViewer.svelte` (§4.4) — Card per metric with formula + inputs + steps + final_output; deep-link `#metric=<name>`.
  - `MethodologyBadge.svelte` (§4.5) — per-methodology colour map per DESIGN.md §1 OKLCH tokens.
- **Brief renderer pipeline** at `apps/web/src/lib/research/render-brief.ts` — DOMPurify sanitise → marked.parse → AST walk replacing `[fact:<uuid>]` text nodes with mounted `CitationLink` components. New deps `marked@^14` (MIT) + `dompurify@^3` (MPL-2.0/Apache-2.0).
- **`/research/[symbol]/audit-trail/[brief_version]/+page.{svelte,server.ts}`** — new nested route; loads brief by symbol+version + renders `AuditTrailViewer` with deep-link support.
- **Update `/research/[symbol]/+page.svelte`** — replace raw `<pre>` body with `render-brief.ts` pipeline + mount `BriefHeader` + `FactTimeline` (compact mode) + Refresh button hooks `useFetch.post` + `useSSE` for `research.brief.refresh.progress`.
- **Storybook stories** per components.md (story files only; Storybook itself is a future UX slice).
- **Playwright e2e** at `apps/web/tests-e2e/research-brief-detail.spec.ts` + `research-audit-trail.spec.ts` — auth fixture → navigate → assert components render → click CitationLink → assert FactTimeline highlights → click Refresh → assert version-bump SSE event.
- **Lighthouse a11y** ≥ 95 on both research routes (extends `lighthouserc.cjs`).

## Capabilities

- `research`: adds visual surface for brief + audit-trail + fact-timeline; no backend changes.

## Impact

- New code under `apps/web/src/lib/components/research/`, `apps/web/src/lib/research/`, `apps/web/src/routes/(app)/research/[symbol]/`, `apps/web/tests-e2e/`.
- 2 frontend deps added (marked, dompurify) — license-boundary CI verifies MIT/Apache compatibility.
- Lighthouse threshold extended from W1's existing config.
- Backend untouched — R5 routes unchanged.

## Prerequisites

R5 archived (✓ 2026-05-06). W1 archived (✓ 2026-05-06).

## Out of scope

- LLM-driven prose enhancements (R5's body markdown is the source of truth).
- Multi-tenant style overrides (v2 SaaS).
- "As-of replay" comparison view (deferred to v1.5 per R5 proposal).

## Acceptance

- All 5 components ship Storybook stories matching components.md verbatim.
- `/research/AAPL` renders BriefHeader + body markdown with inline CitationLink chips + compact FactTimeline.
- `/research/AAPL/audit-trail/1` renders AuditTrailViewer with deep-link `#metric=forward_pe` opening that entry.
- Lighthouse a11y ≥ 95 on both routes in CI.
- Playwright e2e specs pass.
