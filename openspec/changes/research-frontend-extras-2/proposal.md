# Proposal: research-frontend-extras-2

> **Continuation of `research-frontend-extras` (PR #113).** Ships the remaining JTBD-4 / FR70 frontend surface: full markdown→HTML brief body rendering (marked + isomorphic-dompurify), `FactTimeline.svelte` + `AuditTrailViewer.svelte`, the nested `/research/[symbol]/audit-trail/[brief_version]` route, Playwright e2e specs, and Lighthouse a11y threshold extension to `/research/*` routes. **Storybook stories are scope-deferred** to a future `research-frontend-storybook` slice (see "Out of scope" below).

## Why

The previous slice (PR #113) shipped a scope-reduced minimum-viable surface: MethodologyBadge + CitationLink + BriefHeader + `parseCitations` helper + page rewrite. The brief body still renders as plain text inside a `<pre>` with `white-space: pre-wrap` — no markdown→HTML, no link/list/heading rendering, no audit-trail visualization, no fact-timeline UI.

Operator JTBD-4 ("can I trust this brief?") is partially satisfied by clickable citation chips but missing two pillars:

1. **Visual derivation chain** — operators cannot see the formula → inputs → intermediate_steps → final_output chain that produced each numeric. The data is already in `BriefResponse.audit_trail` (R5); the frontend just doesn't render it.
2. **Fact provenance timeline** — facts arrive over time from EDGAR / FRED / news adapters; the current detail page shows them as a flat unordered list. A compact chronological timeline with retrieval-method badges makes provenance scannable.

The R5 backend has both surfaces ready: `audit_trail` is embedded in every `BriefResponse`; `/api/v1/research/facts/{symbol}` returns the bitemporal `facts` rows. This slice is **pure frontend wiring** + 2 small dep installs.

## What

### Dependencies (additive)

- `marked` (MIT) — fast markdown → HTML; configurable to disable raw HTML passthrough so all sanitization happens at one layer.
- `isomorphic-dompurify` (MPL-2.0) — DOMPurify wrapper that works on both SSR (node `jsdom`) and client. Choose this over raw `dompurify` to keep the body-rendering helper single-implementation across SSR/CSR.

Both are MIT/MPL — the existing `license-boundary-check.yml` workflow only enforces the AGPL boundary for Python (`apps/api/` vs `apps/openbb-sidecar/`); frontend deps are unaffected.

### `lib/research/render-brief-body.ts` (NEW)

```ts
export function renderBriefBody(markdown: string): string {
  // marked first: produces raw HTML (no inline sanitization).
  const raw = marked.parse(markdown, { async: false, breaks: true, gfm: true }) as string;
  // DOMPurify enforces the sanitization boundary (strip <script>, dangerous attrs).
  return DOMPurify.sanitize(raw, {
    USE_PROFILES: { html: true },
    ALLOWED_TAGS: ['p', 'strong', 'em', 'h1', 'h2', 'h3', 'ul', 'ol', 'li', 'a', 'code', 'pre', 'blockquote', 'br', 'span'],
    ALLOWED_ATTR: ['href', 'class', 'data-fact-id'],
    ALLOW_DATA_ATTR: true
  });
}
```

The pipeline preserves the existing `[fact:<uuid>]` citation markers (marked treats them as raw text); the symbol detail page splits the rendered HTML on the citation marker pattern at the Svelte template layer (existing `parseCitations` helper).

### `FactTimeline.svelte` (NEW)

Compact-mode-only for v1 (full + as-of modes deferred). Props:

```ts
export type FactTimelineProps = {
  facts: FactRow[];
  maxItems?: number;     // default 20
  highlightFactId?: string | null;  // hover/click integration with CitationLink
};
```

Renders each fact as a row: `effective_from` → `fact_kind` (badge) → value (numeric or text) → retrieval-method icon (lucide-svelte) → source link. Sorted descending by `effective_from`. Bitemporal "as-of" toggle deferred (would need a date picker + `?asOf=` query on `/facts/{symbol}`).

### `AuditTrailViewer.svelte` (NEW)

Accordion of `AuditTrailEntry` rows. Each accordion item shows:

```
[formula text]                                         ▼ expand
  inputs: [{fact_id, value}, ...]   ← clickable fact_id → CitationLink
  intermediate_steps: [step1, step2, ...]
  final_output: <value or label>
```

Props:

```ts
export type AuditTrailViewerProps = {
  entries: AuditTrailEntry[];
  factById?: Map<string, FactRow>;  // optional; enables CitationLink in inputs
  deepLinkIndex?: number | null;    // scroll-into-view + open
};
```

Deep-link support: opening `/research/[symbol]/audit-trail/[brief_version]?entry=3` scrolls the 3rd entry into view + auto-expands its accordion.

### `/research/[symbol]/audit-trail/[brief_version]` route (NEW)

Files:

- `+page.server.ts` — fetches `/briefs/{symbol}` + `/facts/{symbol}` in parallel; validates `params.brief_version === String(brief.version)`; if mismatch, redirects to the current version's audit-trail (operator-friendly). Returns `{ brief, facts, requestedVersion }`.
- `+page.svelte` — top-of-page `BriefHeader` (read-only; no refresh CTA) + `AuditTrailViewer` taking `brief.audit_trail` + `factById` map.

Sidebar `meta` export with `hidden: true` (deep route; not a top-level nav entry).

### Brief detail page rewrite (`/research/[symbol]/+page.svelte`)

Replaces the current text-segment splitter with:

1. `renderBriefBody(body)` → HTML string.
2. Walk the HTML at a higher level: split on `[fact:<uuid>]` substring tokens BEFORE sanitization (already done by `parseCitations`); produce a list of `{kind: 'text'|'citation', value}` segments where text values are sanitized HTML.
3. Render each text segment via `{@html sanitizedHtml}` and each citation via `<CitationLink>`.
4. Append `<FactTimeline>` underneath the brief body.
5. Add "View audit trail →" link to `/research/[symbol]/audit-trail/[brief.version]`.

### Lighthouse a11y threshold extension

Extend the existing `lighthouserc.json` (or equivalent CI config) to assert the `/research/*` routes pass the same a11y ≥ 95 budget as the rest of the app.

### Tests

- **Vitest unit**: `lib/research/render-brief-body.test.ts` — asserts `<script>` injection is stripped, `onerror` attrs removed, links keep `href`, markdown headings/lists render.
- **Vitest unit**: existing `parse-citations.ts` already has implicit coverage via the page renders; add explicit unit tests in `lib/research/parse-citations.test.ts` for boundary conditions.
- **Playwright e2e**: `tests-e2e/research-brief-detail.spec.ts` — login, visit `/research/AAPL`, assert markdown rendering, click first CitationLink, click "View audit trail", assert AuditTrailViewer shows.
- **Playwright e2e**: `tests-e2e/research-audit-trail.spec.ts` — direct navigation to `/research/AAPL/audit-trail/1`, accordion expand/collapse, deep-link `?entry=N` scroll behavior.

## Out of scope

- **Storybook stories** — scope-deferred to a future `research-frontend-storybook` slice. Rationale: (a) component coverage is already provided by Playwright e2e + Vitest unit; (b) Storybook setup adds ~6 devDeps + 2 config files + potentially a new CI job — disproportionate for 3-5 components; (c) the slice is more useful once the frontend surface is wider. Listed in retro carry-forward.
- **Bitemporal "as-of" mode for `FactTimeline`** — requires a date picker + `?asOf=` query parameter on `/facts/{symbol}` (backend doesn't accept it today). Future enhancement.
- **By-version brief endpoint** (`/briefs/{symbol}/versions/{n}`) — current `[brief_version]` URL parameter is decorative (validated against the current brief's version, redirects on mismatch). Backend endpoint can land later without URL changes.
- **Real Telegram / Hermes integration smoke tests** — out of slice scope (different domain).
