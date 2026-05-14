# Tasks: portfolio-dashboard-mvp

- [ ] 1. `apps/web/src/lib/portfolio/types.ts` (NEW) — TS mirrors of `EquitySnapshotOut`, `PositionOut`, `PositionListOut`, `PortfolioSummaryOut`, `EquitySnapshotListOut` (Decimal-as-string + ISO 8601 datetime-as-string).
- [ ] 2. `apps/web/src/lib/portfolio/format.ts` (NEW) — pure helpers `formatMoney(value, currency)` + `formatPercent(value)` (display-only via `Intl.NumberFormat`; null/zero/signed cases).
- [ ] 3. `apps/web/src/lib/portfolio/sparkline.ts` (NEW) — pure `buildSparklinePath(values: number[], width: number, height: number): string` returning an SVG `d` attribute; handles 0/1/N points; clamps both axes.
- [ ] 4. `apps/web/src/lib/components/PortfolioSummary.svelte` (NEW) — 4-cell grid card: total value + day P&L (coloured by sign, "—" when null) + cash + position count. Uses `formatMoney` + `formatPercent`.
- [ ] 5. `apps/web/src/lib/components/EquitySparkline.svelte` (NEW) — single SVG path from `EquitySnapshotOut[]`; ~240×72; hover tooltip (`<title>`); no chart lib.
- [ ] 6. `apps/web/src/routes/(app)/portfolio/+page.server.ts` (NEW) — `Promise.all` over the 3 endpoints with cookie forwarding; surfaces `loadError` on any 5xx/throw.
- [ ] 7. `apps/web/src/routes/(app)/portfolio/+page.svelte` — replace `PlaceholderCard` body: summary card + sparkline + positions table (existing `DataTable` reused) OR `EmptyState` when all empty OR `loadError` alert. Positions table renders "—" for null `last_price` / `unrealized_pnl` / `avg_entry_price`.
- [ ] 8. `apps/web/tests/portfolio-page.test.ts` (NEW) — 6 vitest cases (happy / empty / 503 / negative-day-pnl / null-day-pnl / null-position-fields).
- [ ] 9. `apps/web/tests/sparkline.test.ts` (NEW) — pure tests of `buildSparklinePath` (0/1/2/N points + clamping).
- [ ] 10. `apps/web/tests/portfolio-format.test.ts` (NEW) — pure tests of `formatMoney` + `formatPercent` (signed/unsigned/null/zero).
- [ ] 11. `apps/web/src/lib/components/PortfolioSummary.stories.ts` + `EquitySparkline.stories.ts` — 3 variants each (loaded / empty / negative).
- [ ] 12. Vitest + `pnpm check` (svelte-check) + `pnpm build` green locally.
- [ ] 13. Push + open PR with §4.5 self-review pre-populated.
- [ ] 14. Wait for CI all-green (15 checks incl. Lighthouse a11y ≥95).
