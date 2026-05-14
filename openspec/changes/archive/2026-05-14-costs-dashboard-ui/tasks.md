# Tasks: costs-dashboard-ui

- [ ] 1. `apps/web/src/lib/costs/types.ts` (NEW) — TS mirrors of `CostSummaryDTO`, `CostByProviderDTO`, `CostPerTradeDTO`, `PerProviderBreakdown`.
- [ ] 2. `apps/web/src/lib/costs/format.ts` (NEW) — pure `costPerTradeColour(value: number | null): 'success' | 'accent' | 'destructive'`.
- [ ] 3. `apps/web/src/lib/components/CostsSummaryCard.svelte` (NEW) — 3-cell grid card with total / calls / cost-per-trade.
- [ ] 4. `apps/web/src/lib/components/CostPerTradeCard.svelte` (NEW) — big-number card with tier colour.
- [ ] 5. `apps/web/src/routes/(app)/costs/+page.server.ts` (NEW) — `Promise.all` over 3 endpoints with cookie forwarding.
- [ ] 6. `apps/web/src/routes/(app)/costs/+page.svelte` — replace `PlaceholderCard`: header + period + CostsSummaryCard + by-provider DataTable + CostPerTradeCard + EmptyState/error.
- [ ] 7. `apps/web/tests/costs-page.test.ts` (NEW) — 5 vitest cases.
- [ ] 8. `apps/web/tests/costs-format.test.ts` (NEW) — pure test of `costPerTradeColour`.
- [ ] 9. `CostsSummaryCard.stories.ts` + `CostPerTradeCard.stories.ts` — 3 variants each.
- [ ] 10. `pnpm test` + `pnpm check` + `pnpm build` green locally (scoped).
- [ ] 11. Push + open PR with §4.5 self-review.
- [ ] 12. Wait CI all-green (15 checks).
