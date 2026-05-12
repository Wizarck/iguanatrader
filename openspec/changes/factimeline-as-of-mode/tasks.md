# Tasks: factimeline-as-of-mode

- [ ] 1. Backend: `GET /facts/{symbol}?as_of=<iso>` query param + ValidationError on malformed datetime
- [ ] 2. Frontend page: as-of state + datetime input + Apply + Reset buttons; client-side refetch
- [ ] 3. FactTimeline: `asOf` prop + visual indicator in header
- [ ] 4. Mock-fastapi: honour `?as_of=` (returns 1-row subset to simulate the bitemporal filter)
- [ ] 5. Local lint + svelte-check verde
- [ ] 6. Push + open PR + wait CI green
- [ ] 7. Merge + archive + retro fill
