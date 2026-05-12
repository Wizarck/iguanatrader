# Retrospective: research-citation-renderer-refactor

> **Forward-authored** — fill at archive.

- **PR**: TBD (merged TBD, squash `TBD`).
- **Archive path**: `openspec/changes/archive/2026-05-12-research-citation-renderer-refactor/`
- **Lines shipped**: TBD insertions / TBD deletions across TBD files. CI TBD.

## What worked

- TBD

## What didn't

- TBD

## Carry-forward

- **Rich hover-tooltip for inline chips** — `title` attribute is browser-native; a custom CSS-only popover with retrieval-method icon + retrieved_at would improve UX. Future visual-polish slice (no functional impact).

## Pattern usage

- **Marker pre-pass → marked → DOMPurify** as the canonical pipeline for embedding domain-specific tokens (`[fact:<uuid>]`) inside markdown. Three single-purpose stages; each stage's output is the next stage's input. No DOM hydration needed, SSR + CSR identical.
- **`ADD_ATTR` over `ALLOWED_ATTR`** for security-sensitive attrs like `target` — DOMPurify's default strip list contains attrs that are safe when paired with mitigations (here `target="_blank"` always pairs with `rel="noopener noreferrer"`). Use `ADD_ATTR` to extend without weakening the default safe set.
