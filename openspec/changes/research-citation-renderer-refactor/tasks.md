# Tasks: research-citation-renderer-refactor

- [ ] 1. Rewrite `lib/research/render-brief-body.ts`: signature `(markdown, factById?)`, marker pre-pass before marked, ADD_ATTR for `target`
- [ ] 2. Simplify `/research/[symbol]/+page.svelte`: single `{@html renderedHtml}` block, remove parseCitations + per-segment loop
- [ ] 3. Add inline citation chip CSS (`:global(.citation-chip)` + hover + broken variant)
- [ ] 4. Delete `lib/research/parse-citations.ts` + `tests/parse-citations.test.ts` (orphaned)
- [ ] 5. Extend `tests/render-brief-body.test.ts` with chip-injection cases (URL, no URL, unresolved, paragraph preservation, escape injection)
- [ ] 6. Update Playwright `research-brief-detail.spec.ts`: assert `a.citation-chip` static elements
- [ ] 7. Local vitest + svelte-check verde
- [ ] 8. Push + open PR + wait CI green
- [ ] 9. Merge + archive + retro fill
