# Proposal: research-citation-renderer-refactor

> **Fix multi-paragraph artifacts** in the brief-detail page citation renderer (pre-flag from PR #115 retro). Single-pass markdown→HTML pipeline with citations baked inline as static `<a>`/`<span>` chips — block structure (paragraphs, headings, lists) preserved.

## Why

PR #115 retro pre-flag candidate:

> Per-segment markdown rendering produces multi-paragraph artifacts between citation chips. The current pipeline splits the brief markdown on `[fact:<uuid>]` markers BEFORE running marked, then renders each text fragment via marked+DOMPurify independently. Adjacent fragments lose their shared paragraph context (the text "Strong quarter per [fact:abc] and growing earnings per [fact:def]." renders as 3 separate `<p>` elements instead of one).

Current flow: `parseCitations(body)` → array of text/citation segments → page iterates each → `renderBriefBody(text)` per text fragment → `<CitationLink>` per citation. Three separate marked invocations across the example sentence above means three separate `<p>` blocks.

Fix: replace the markers inline BEFORE marked runs, render the entire body as one HTML string, sanitize once.

## What

### `lib/research/render-brief-body.ts` rewritten

New signature: `renderBriefBody(markdown: string, factById?: Map<string, FactProvenance>): string`.

Pipeline:

1. **Pre-pass**: replace each `[fact:<uuid>]` marker with inline citation chip HTML (anchor when a `source_url` exists, span otherwise). Uses the optional `factById` map for provenance; unresolved markers render as broken-citation `<span>` chips.
2. **marked**: parses the full body (with chips inlined) to HTML in a single invocation.
3. **DOMPurify**: sanitizes the result. Strict allow-list now extended with `target` + `rel` so the chip's `target="_blank"` survives.

The chip HTML mirrors `CitationLink.svelte`'s visual surface but is static (no Svelte runtime / hover-tooltip JS — uses the browser-native `title` attribute for the tooltip). Operators trade rich-hover for correct block structure; the audit-trail page (which uses CitationLink as a real Svelte component inside `AuditTrailViewer`) is unaffected.

### `/research/[symbol]/+page.svelte` simplified

Old:
```svelte
{#each segments as seg, i (i)}
  {#if seg.kind === 'text'}
    {@html renderBriefBody(seg.value)}
  {:else}
    <CitationLink ... />
  {/if}
{/each}
```

New:
```svelte
{@html renderBriefBody(body, factById)}
```

Single `{@html}` injection. Block boundaries preserved by marked's normal parser run.

### `lib/research/parse-citations.ts` + its test file removed

The helper is no longer called by the page. `CitationLink.svelte` stays (used by `AuditTrailViewer`).

### Tests

- **Updated `render-brief-body.test.ts`**: add cases for inline citation injection (with URL, without URL, unresolved), markdown-block-preservation (markers inside paragraphs/lists yield single `<p>`/`<ul>` not split blocks).
- **Removed `parse-citations.test.ts`**: source file deleted.
- **Playwright `research-brief-detail.spec.ts`**: assertions updated — the citation chip is now a static anchor element (target=_blank, data-fact-id), no longer a Svelte component instance. Heading + bullet list visibility assertions stay.

## Out of scope

- **Rich hover-tooltip for inline chips** — `title` attribute is the browser-native tooltip. A custom CSS-only popover is a future visual polish slice.
- **CitationLink.svelte removal** — still used by AuditTrailViewer for the inputs section. Don't touch it.
- **Marked custom token extension** — heavier path that produces the same result; the marker-pre-replace approach is simpler + equivalent.
