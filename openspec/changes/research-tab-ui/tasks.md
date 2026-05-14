# Tasks: research-tab-ui

- [ ] 1. `apps/web/src/lib/research/recent.ts` (NEW) — pure `readRecent(storageKey)` + `recordRecent(storageKey, symbol, max=8)`.
- [ ] 2. `apps/web/src/lib/components/SymbolSearchCard.svelte` (NEW) — TextInput + pattern validation + submit → `goto('/research/{symbol}')`.
- [ ] 3. `apps/web/src/lib/components/RecentSymbolsList.svelte` (NEW) — reads localStorage, renders pill list, EmptyState when none.
- [ ] 4. `apps/web/src/routes/(app)/research/+page.svelte` — replace `PlaceholderCard` body: header + SymbolSearchCard + RecentSymbolsList.
- [ ] 5. `apps/web/src/routes/(app)/research/[symbol]/+page.svelte` — `$effect` hook records visited symbol via `recordRecent` + localStorage.setItem.
- [ ] 6. `apps/web/tests/research-tab.test.ts` (NEW) — 5 vitest cases.
- [ ] 7. `apps/web/tests/research-recent.test.ts` (NEW) — pure tests (4 cases).
- [ ] 8. `SymbolSearchCard.stories.ts` + `RecentSymbolsList.stories.ts` — 3 variants each.
- [ ] 9. `pnpm test` + `pnpm check` + `pnpm build` green locally (scoped).
- [ ] 10. Push + open PR with §4.5 self-review.
- [ ] 11. Wait CI all-green (15 checks incl. Lighthouse a11y ≥95).
