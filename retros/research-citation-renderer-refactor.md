# Retrospective: research-citation-renderer-refactor

> **Forward-authored** — fill at archive.

- **PR**: [#118](https://github.com/Wizarck/iguanatrader/pull/118) (merged 2026-05-12, squash `a1c7c18`).
- **Archive path**: `openspec/changes/archive/2026-05-12-research-citation-renderer-refactor/`
- **Lines shipped**: 315 insertions / 153 deletions across 9 files. CI 12/12 verde **al primer push** (zero fix rounds; 1 local vitest round caught DOMPurify `target` stripping).

## What worked

- **Marker pre-pass before marked** is the right architecture for embedding domain-specific tokens in markdown: each stage's output is the next stage's input, single sanitization boundary, SSR + CSR identical, no DOM hydration needed.
- **Local vitest caught the DOMPurify `target` strip** in <1s before push — the assertion `expect(html).toContain('target="_blank"')` failed on the first run because DOMPurify's default safety list silently drops `target`. Lesson: vitest assertions on **specific attribute substrings** in sanitized HTML are the right granularity for catching DOMPurify config gotchas (a coarser check like "html contains the anchor" would have missed the issue).
- **HTML escape inside the chip renderer** (`escapeHtml` on `source_id`, `source_url`, `factId`) gave us defense-in-depth — even if a `source_url` contained `javascript:`, marked + DOMPurify would still strip it, but the escape ensures we don't pass malformed HTML into marked in the first place.
- **Deleting `parse-citations.ts` + its test file** removed ~50 lines of orphaned code. Better than keeping "just in case" — git history preserves it if ever needed.

## What didn't

- **DOMPurify `target` attribute strip** wasn't documented anywhere; I had to discover it via failing test. Pre-flag candidate: when allowing security-sensitive HTML attrs (`target`, `srcdoc`, `formaction`), check DOMPurify's `defaults.ts` first — many are in `FORBID_ATTR` even when added to `ALLOWED_ATTR`. Use `ADD_ATTR` to extend without weakening the default safe set.
- **The new approach loses the rich JS hover-tooltip** from `CitationLink.svelte` (browser-native `title` attribute now). Operators get correct block structure + functional tooltip via OS browser, but the hover popover with retrieval-method icon + formatted timestamp is gone for inline brief-body chips. The full `CitationLink` component stays alive for `AuditTrailViewer` inputs.

## Carry-forward

- **CSS-only hover popover for inline chips** — replace browser-native `title` with a styled `:hover::after` overlay rendering the same tooltip content. Pure CSS, no JS. Future visual-polish slice.

## Pattern usage

- **Pre-pass → render → sanitize** as the canonical pipeline for embedding tokens in markdown. Codifies the architecture for future similar surfaces (e.g. inline metric chips, inline ticker chips).
- **`ADD_ATTR` over `ALLOWED_ATTR`** for sensitive attrs — keeps DOMPurify's default forbid list intact while permitting the one attr you need.

## Carry-forward

- **Rich hover-tooltip for inline chips** — `title` attribute is browser-native; a custom CSS-only popover with retrieval-method icon + retrieved_at would improve UX. Future visual-polish slice (no functional impact).

## Pattern usage

- **Marker pre-pass → marked → DOMPurify** as the canonical pipeline for embedding domain-specific tokens (`[fact:<uuid>]`) inside markdown. Three single-purpose stages; each stage's output is the next stage's input. No DOM hydration needed, SSR + CSR identical.
- **`ADD_ATTR` over `ALLOWED_ATTR`** for security-sensitive attrs like `target` — DOMPurify's default strip list contains attrs that are safe when paired with mitigations (here `target="_blank"` always pairs with `rel="noopener noreferrer"`). Use `ADD_ATTR` to extend without weakening the default safe set.
