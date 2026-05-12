# Retrospective: research-brief-by-version-endpoint

> **Forward-authored** — fill at archive.

- **PR**: [#117](https://github.com/Wizarck/iguanatrader/pull/117) (merged 2026-05-12, squash `cface64`).
- **Archive path**: `openspec/changes/archive/2026-05-12-research-brief-by-version-endpoint/`
- **Lines shipped**: 343 insertions / 23 deletions across 9 files. CI 12/12 verde **al primer push** (zero fix rounds).

## What worked

- **Mirror-then-narrow pattern for `brief_by_symbol_and_version`**: copy `latest_brief`, swap `order_by(...).limit(1)` for `where(version=...)`. The UNIQUE constraint guarantees at most one row, so no ordering needed. Pre-flag confirmed: repository methods filtering on a UNIQUE-constrained tuple don't need ORDER BY or LIMIT 1 — the constraint IS the LIMIT 1.
- **Backend → mock → e2e** pipeline finished cleanly: route lands, mock-fastapi mirrors the route, e2e test exercises both happy path + 404. The mock-update step is what makes the e2e meaningful — without it, Playwright would hit the real (unreachable) FastAPI.
- **Reused existing `NotFoundError`** from `shared.errors` instead of inventing a research-specific 404 type — the slice-5 global handler in `apps/api/src/iguanatrader/api/errors.py` already maps it to RFC 7807 `urn:iguanatrader:error:not-found`. No new error class needed.
- **Retro carry-forward → slice → carry-forward burndown** happens cleanly: PR #115's decorative-URL flag became this slice's load-bearing wiring; this slice's retro lists "list all versions" as the next layer down.

## What didn't

- **Zero local mypy validation possible** for the new code in this venv (project deps missing). CI mypy was the first true check. It passed first try, but that's luck — the prior slice #116 hit a mypy-only issue (str → Literal cast). Pre-flag candidate: when touching FastAPI route signatures or repo methods with Literal-typed fields, the safe path is `cast` early rather than rely on CI to find the type error.

## Carry-forward

- **`GET /briefs/{symbol}/versions`** (list all versions for a symbol) — not requested by JTBD-4 yet; defer until the version-picker UI surface needs it. Mechanical: copy `latest_brief` but order by `version DESC` without `LIMIT 1`, return list.

## Pattern usage

- **Decorative-URL → load-bearing** burndown via a backend-first slice. The frontend route landed in PR #115 with the version param validated against current; this slice promotes it to a real fetch-by-version. Sets the pattern for future "I shipped the surface but the data path is half-wired" carry-forwards.

## Carry-forward

- **`GET /briefs/{symbol}/versions`** (list all versions) — not requested by JTBD-4; defer until the version-picker UI surface needs it.

## Pattern usage

- Promotes a "decorative URL param" (carry-forward from PR #115) to load-bearing with a backend-first slice — the route + repo method land first, then the frontend loader swaps the fetch URL. No new schema needed (`UNIQUE (tenant_id, symbol_universe_id, version)` already in R5).
