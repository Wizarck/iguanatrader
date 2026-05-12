# Retrospective: research-brief-by-version-endpoint

> **Forward-authored** — fill at archive.

- **PR**: TBD (merged TBD, squash `TBD`).
- **Archive path**: `openspec/changes/archive/2026-05-12-research-brief-by-version-endpoint/`
- **Lines shipped**: TBD insertions / TBD deletions across TBD files. CI TBD.

## What worked

- TBD

## What didn't

- TBD

## Carry-forward

- **`GET /briefs/{symbol}/versions`** (list all versions) — not requested by JTBD-4; defer until the version-picker UI surface needs it.

## Pattern usage

- Promotes a "decorative URL param" (carry-forward from PR #115) to load-bearing with a backend-first slice — the route + repo method land first, then the frontend loader swaps the fetch URL. No new schema needed (`UNIQUE (tenant_id, symbol_universe_id, version)` already in R5).
