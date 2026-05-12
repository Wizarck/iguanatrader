# Tasks: research-brief-by-version-endpoint

- [ ] 1. `ResearchRepository.brief_by_symbol_and_version(symbol, version)` — repository method
- [ ] 2. `GET /api/v1/research/briefs/{symbol}/versions/{version}` route in `api/routes/research.py`
- [ ] 3. Update `[brief_version]/+page.server.ts` to fetch via new endpoint (drop redirect-on-mismatch)
- [ ] 4. Extend `mock-fastapi.mjs` with the versions route (accepts 1..3, 404 otherwise)
- [ ] 5. Update `tests-e2e/research-audit-trail.spec.ts` to replace redirect test with 404 assertion
- [ ] 6. Unit test `tests/unit/contexts/research/test_brief_by_version.py`
- [ ] 7. Local lint + svelte-check verde
- [ ] 8. Push + open PR + wait CI green
- [ ] 9. Merge + archive + retro fill
