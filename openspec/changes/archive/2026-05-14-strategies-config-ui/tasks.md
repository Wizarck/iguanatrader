# Tasks: strategies-config-ui

- [ ] 1. `apps/web/src/lib/strategies/types.ts` (NEW) — TS mirrors of `StrategyConfigOut`, `StrategyConfigIn`, `StrategyConfigListOut`.
- [ ] 2. `apps/web/src/lib/components/forms/TextInput.svelte` (NEW) — `{ name, label, value, type='text', required?, pattern?, helpText?, error? }`.
- [ ] 3. `apps/web/src/lib/components/forms/Select.svelte` (NEW) — `{ name, label, value, options: {value,label}[], error? }`.
- [ ] 4. `apps/web/src/lib/components/forms/Textarea.svelte` (NEW) — `{ name, label, value, rows?=8, monospace?=true, error? }`.
- [ ] 5. `apps/web/src/lib/components/forms/Checkbox.svelte` (NEW) — `{ name, label, checked }`.
- [ ] 6. `apps/web/src/routes/(app)/strategies/+page.server.ts` (NEW) — `load` fn fetches `GET /strategies` with cookie forwarding; returns `{ strategies, loadError? }`.
- [ ] 7. `apps/web/src/routes/(app)/strategies/+page.svelte` — replace `PlaceholderCard` body with header (h1 + "Nueva estrategia" button) + `DataTable` (cols + Action buttons) + `EmptyState` + `loadError` alert.
- [ ] 8. `apps/web/src/routes/(app)/strategies/[symbol]/+page.server.ts` (NEW) — `load` fn (handles `params.symbol === 'new'` + edit modes) + `export const actions = { upsert, disable }`.
- [ ] 9. `apps/web/src/routes/(app)/strategies/[symbol]/+page.svelte` (NEW) — form (symbol if new, strategy_kind dropdown, params textarea with kind-defaults, enabled checkbox) + Submit + Cancel + (edit mode) Deshabilitar button + inline + form-level error rendering.
- [ ] 10. `apps/web/tests/strategies-list-page.test.ts` (NEW) — 5 vitest cases (happy / empty / 503 / row-edit / disable).
- [ ] 11. `apps/web/tests/strategies-form-page.test.ts` (NEW) — 8 vitest cases (new / edit pre-fill / kind-defaults-on-change / JSON invalid / symbol pattern invalid / success redirect / disable / 404 load).
- [ ] 12. Storybook stories: `TextInput.stories.ts` + `Select.stories.ts` + `Textarea.stories.ts` + `Checkbox.stories.ts` — 3 variants each.
- [ ] 13. `pnpm test` + `pnpm check` (svelte-check) + `pnpm build` green locally.
- [ ] 14. Push + open PR with §4.5 self-review.
- [ ] 15. Wait for CI all-green (15 checks incl. Lighthouse a11y ≥95).
