# Proposal: research-frontend-extras

> **Scope-reduced ship of the original `research-frontend-components` spec.** Delivers the JTBD-4 visibility win (clickable citation chips in the brief body + MethodologyBadge + BriefHeader) without the full 5-component / Playwright / Storybook surface. Remaining components (FactTimeline + AuditTrailViewer) + audit-trail nested route + Playwright + Storybook + Lighthouse threshold extension are deferred to a future `research-frontend-extras-2` slice when frontend infra (marked + DOMPurify deps, Playwright fixtures) is the focus.

## Why

Slice research-frontend-settings-page (PR #108) closed the R6 Web UI gap (Settings toggle). The remaining R5 brief surface still renders `[fact:<uuid>]` markers as raw text inside a `<pre class="markdown">` block — operator cannot click a citation. JTBD-4 ("show your work — anti-hallucination") is structurally enforced server-side (synthesizer rejects invented UUIDs) but invisible client-side.

This slice closes the **visibility half** of JTBD-4: brief body is parsed for `[fact:<uuid>]` markers, each replaced inline with a `CitationLink` chip that exposes the source URL + retrieval method on hover. The `BriefHeader` lifts symbol/version/methodology/freshness above the body so the operator gets context at-a-glance.

Hyper-minimal scope: NO new frontend deps (no marked, no DOMPurify) — hand-rolled marker substitution over the existing raw markdown render preserves the `<pre>` body shape but injects mounted CitationLink chips at the marker positions. Full markdown→HTML rendering (heading / list / link / code) is **deferred** to the future slice when the marked+DOMPurify deps land + license-boundary CI accepts them.

## What

5 NEW files:

1. `apps/web/src/lib/components/research/MethodologyBadge.svelte` — per-methodology colour pill (5 methodologies + neutral fallback).
2. `apps/web/src/lib/components/research/CitationLink.svelte` — inline citation chip with hover tooltip (sourceLabel + retrievedAt + method).
3. `apps/web/src/lib/components/research/BriefHeader.svelte` — symbol + version + MethodologyBadge + synthesizedAt + Refresh CTA.
4. `apps/web/src/lib/research/parse-citations.ts` — pure-TS helper that splits brief markdown text by `[fact:<uuid>]` markers and returns alternating `{ kind: 'text'; value: string } | { kind: 'citation'; factId: string }` segments.
5. **MODIFIED** `apps/web/src/routes/(app)/research/[symbol]/+page.svelte` — replaces the inline header HTML + raw `<pre>` with `BriefHeader` + parsed brief body (text segments rendered as `<span>`, citation segments as `<CitationLink>`).

Plus 1 helper for citation hover data:

6. The brief payload from `/api/v1/research/briefs/{symbol}` exposes `citations: [{fact_id: uuid}]`. To get sourceLabel + retrievedAt + method per citation, the page does a parallel fetch of `/api/v1/research/facts/{symbol}` (already exists from R5) and indexes facts by id. Wire-up only — no new backend.

## Out of scope (deferred to `research-frontend-extras-2`)

- `FactTimeline.svelte` (compact + full + as-of modes; bitemporal axis rendering).
- `AuditTrailViewer.svelte` (accordion + deep-link).
- `/research/[symbol]/audit-trail/[brief_version]/+page.{svelte,server.ts}` nested route.
- marked + DOMPurify deps (needs license-boundary CI check).
- Playwright e2e (`research-brief-detail.spec.ts`).
- Storybook stories (no Storybook infra installed).
- Lighthouse a11y threshold extension to research routes.

## Acceptance criteria

1. `/research/AAPL` renders `<BriefHeader>` band + brief body with inline citation chips at every `[fact:<uuid>]` marker.
2. Clicking a CitationLink opens its `sourceUrl` in a new tab; hovering reveals tooltip with `sourceLabel` + retrievedAt.
3. Methodology pill colour is consistent across the 5 methodologies (5 OKLCH tokens declared inline; future DESIGN.md migration is a follow-up).
4. Existing Refresh button + state behaviour preserved (no regression).
5. lint (eslint/prettier if configured) + svelte-check + CI green.

## Estimated effort

~3-4h, ~400 LoC frontend.
