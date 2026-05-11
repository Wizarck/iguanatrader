# Tasks: research-frontend-extras-2

## Deps + helper

- [ ] 1. `pnpm add marked isomorphic-dompurify` + `pnpm add -D @types/dompurify` in `apps/web/`
- [ ] 2. Create `apps/web/src/lib/research/render-brief-body.ts` — marked + DOMPurify pipeline
- [ ] 3. Vitest: `apps/web/src/lib/research/render-brief-body.test.ts` — sanitization (XSS rejection)
- [ ] 4. Vitest: `apps/web/src/lib/research/parse-citations.test.ts` — boundary tests

## Components

- [ ] 5. `apps/web/src/lib/components/research/FactTimeline.svelte`
- [ ] 6. `apps/web/src/lib/components/research/AuditTrailViewer.svelte`

## Routes

- [ ] 7. `apps/web/src/routes/(app)/research/[symbol]/audit-trail/[brief_version]/+page.server.ts`
- [ ] 8. `apps/web/src/routes/(app)/research/[symbol]/audit-trail/[brief_version]/+page.svelte`
- [ ] 9. Update `/research/[symbol]/+page.svelte` — markdown rendering + FactTimeline + audit-trail link

## E2E

- [ ] 10. `apps/web/tests-e2e/research-brief-detail.spec.ts`
- [ ] 11. `apps/web/tests-e2e/research-audit-trail.spec.ts`

## CI

- [ ] 12. Extend Lighthouse a11y threshold to `/research/*` routes
- [ ] 13. Verify pnpm install + svelte-check + vitest + Playwright locally
- [ ] 14. Push branch + open PR + wait CI green
- [ ] 15. Merge + archive openspec + fill retro
