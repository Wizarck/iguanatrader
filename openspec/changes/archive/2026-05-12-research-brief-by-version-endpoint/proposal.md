# Proposal: research-brief-by-version-endpoint

> **Backend route + repository method + frontend wiring** for fetching a specific brief version. Promotes the `[brief_version]` URL param in `/research/[symbol]/audit-trail/[brief_version]` from decorative (carry-forward retro #115) to load-bearing.

## Why

PR #115 (`research-frontend-extras-2`) shipped the audit-trail nested route. The route's `[brief_version]` URL parameter was wired but **decorative**: the loader fetched the current brief via `/api/v1/research/briefs/{symbol}` and redirected to the canonical version on mismatch. Operators couldn't actually pull a prior version's audit trail.

Retro carry-forward:

> **`/briefs/{symbol}/versions/{n}` endpoint** — currently the audit-trail URL's `[brief_version]` parameter is decorative (validated against current version, redirects on mismatch). Adding the backend endpoint + swapping the loader to fetch by version is a small follow-up.

This slice closes that gap. Operators can now navigate to `/research/AAPL/audit-trail/3` and inspect the FR70 derivation chain that produced v3 of the AAPL brief — even after v4/v5/... have been synthesized.

## What

### Backend

1. **`ResearchRepository.brief_by_symbol_and_version(symbol, version)`** — mirrors `latest_brief` but filtered by version. Returns `ResearchBrief | None`. The unique constraint on `(tenant_id, symbol_universe_id, version)` (already in schema) guarantees at most one row.

2. **`GET /api/v1/research/briefs/{symbol}/versions/{version}` route** — returns the same `BriefResponse` shape as `/briefs/{symbol}`. Reuses `_project_brief` + `CitationResolver`. 404 RFC 7807 when no brief exists at the requested version.

### Frontend

3. **`/research/[symbol]/audit-trail/[brief_version]/+page.server.ts`** — replaces the "fetch current, validate, redirect on mismatch" logic with a direct fetch of `/briefs/{symbol}/versions/{requestedVersion}`. On 404 → SvelteKit `error(404, ...)`; on success → render the requested version. The redirect-on-mismatch behaviour goes away (no longer needed).

4. **`tests-e2e/mock-fastapi.mjs`** — extend with `/briefs/:symbol/versions/:version` route returning the mock brief shape (same payload as `/briefs/:symbol`, just with `version` echoed from the URL).

5. **`tests-e2e/research-audit-trail.spec.ts`** — drop the "mismatched brief_version redirects to current" test (behaviour is gone); update the happy path to use `/research/AAPL/audit-trail/1` directly.

### Tests

6. **Unit/integration test** for the new repository method — seed two briefs at versions 1 + 2 + verify `brief_by_symbol_and_version` returns the matching one (or `None` for absent versions).

## Out of scope

- **GET all versions for a symbol** (`/briefs/{symbol}/versions`) — not requested by JTBD-4; defer until the version-picker UI surface needs it.
- **Version-specific facts endpoint** — `/facts/{symbol}` already returns all current facts; the version-specific audit trail uses the brief's embedded `audit_trail` field. No new facts surface needed.
