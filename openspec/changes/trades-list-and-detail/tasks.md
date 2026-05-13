# Tasks: trades-list-and-detail

- [ ] 1. `apps/web/src/lib/components/EmptyState.svelte` (NEW) — props `title`, `body`, `hint?` — OKLCH styling matching `PlaceholderCard` but no "future slice" reference
- [ ] 2. `apps/web/src/lib/components/Badge.svelte` (NEW) — props `label`, `variant: 'success' | 'destructive' | 'accent' | 'mute'`
- [ ] 3. `apps/web/src/lib/components/DataTable.svelte` (NEW) — generic typed table with column-config slot pattern + row-click event
- [ ] 4. `apps/web/src/routes/(app)/trades/+page.server.ts` (NEW) — `load` fn fetches `${API_BASE_URL}/api/v1/trades` with cookie forwarding; returns `{ trades, total, loadError? }`
- [ ] 5. `apps/web/src/routes/(app)/trades/+page.svelte` — replace `PlaceholderCard` body with `DataTable` (cols: Symbol, Side, Qty, Mode, State, Opened, Closed) + side/state `Badge` + row navigation to `/trades/{id}` + `EmptyState` when empty + `loadError` alert
- [ ] 6. `apps/web/src/routes/(app)/trades/[id]/+page.server.ts` (NEW) — fetches `/trades/{id}` + `/trades/{id}/fills` in parallel; returns `{ trade, fills, loadError? }`
- [ ] 7. `apps/web/src/routes/(app)/trades/[id]/+page.svelte` (NEW) — summary card + fills table + back link; "Sin fills aún." inline when fills empty
- [ ] 8. `apps/web/tests/trades-list-page.test.ts` (vitest) — 4 cases (happy, empty, 503, side badges)
- [ ] 9. `apps/web/tests/trades-detail-page.test.ts` (vitest) — 4 cases (happy, no fills, 503, back link)
- [ ] 10. `apps/web/src/lib/components/EmptyState.stories.ts` + `Badge.stories.ts` + `DataTable.stories.ts` — 3 variants each
- [ ] 11. `apps/api/tests/integration/test_trades_route_smoke.py` (NEW) — verifies the 3 trades endpoints return their documented shape for a fresh empty tenant
- [ ] 12. Vitest + svelte-check + pnpm test green locally
- [ ] 13. ruff + black + mypy --strict + pytest green locally (api-side smoke test)
- [ ] 14. Push + open PR with §4.5 pre-populated
- [ ] 15. Wait for CI all-green
