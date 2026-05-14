# Tasks: risk-dashboard-ui

- [ ] 1. `apps/web/src/lib/risk/types.ts` (NEW) — TS mirrors of `CapsDTO`, `StateDTO`, `RiskStateResponse`.
- [ ] 2. `apps/web/src/lib/risk/colour.ts` (NEW) — pure `utilisationBarColour(ratio: number): 'success' | 'accent' | 'destructive'`.
- [ ] 3. `apps/web/src/lib/components/RiskCapsCard.svelte` (NEW) — 5-cell grid of caps; OKLCH styling.
- [ ] 4. `apps/web/src/lib/components/RiskUtilisationCard.svelte` (NEW) — 3 utilisation bars with sign-coloured fill + value labels.
- [ ] 5. `apps/web/src/routes/(app)/risk/+page.server.ts` (NEW) — fetches `/api/v1/risk/state` with cookie forwarding.
- [ ] 6. `apps/web/src/routes/(app)/risk/+page.svelte` — replace `PlaceholderCard` body: header + kill-switch indicator + RiskCapsCard + RiskUtilisationCard + capital stat + EmptyState/error.
- [ ] 7. `apps/web/tests/risk-page.test.ts` (NEW) — 5 vitest cases.
- [ ] 8. `apps/web/tests/risk-colour.test.ts` (NEW) — pure test of `utilisationBarColour`.
- [ ] 9. `RiskCapsCard.stories.ts` + `RiskUtilisationCard.stories.ts` — 3 variants each.
- [ ] 10. `pnpm test` + `pnpm check` + `pnpm build` green locally (scoped).
- [ ] 11. Push + open PR with §4.5 self-review.
- [ ] 12. Wait CI all-green (15 checks).
