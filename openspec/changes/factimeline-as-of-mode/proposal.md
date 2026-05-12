# Proposal: factimeline-as-of-mode

> **Backend `?as_of=` query param** on `GET /api/v1/research/facts/{symbol}` + **frontend datetime picker** that drives a refetch. Closes the carry-forward from PR #115 retro: bitemporal "as-of" mode for `FactTimeline`.

## Why

PR #115 retro carry-forward:

> **`FactTimeline` as-of bitemporal mode** — requires a date picker + `?asOf=` query parameter on `/api/v1/research/facts/{symbol}` (backend doesn't accept it today). Future enhancement.

R5 ships a fully bitemporal fact schema (`effective_from` / `effective_to` / `recorded_from` / `recorded_to`) and the repository already has `as_of(symbol, at)` implementing the dual-axis point-in-time predicate. The only missing pieces are: the HTTP surface to invoke it, and a UI that lets the operator pick `at`.

JTBD-4: "Can I trust this brief?" — extends to "Can I reconstruct what we knew at the time the brief was synthesised?". Without `as-of`, the operator only sees the latest fact set, not the snapshot the brief was built from.

## What

### Backend

1. **`GET /api/v1/research/facts/{symbol}?as_of=<iso>`** — optional ISO 8601 query parameter. When present, the route calls `repo.as_of(symbol, at)` instead of `facts_for_symbol(symbol, limit=50)`. Returns the same `list[FactResponse]` shape.

2. **Validation**: invalid datetime → 400 RFC 7807 with `ValidationError`. Future-dated `as_of` is allowed (returns empty set — no facts visible yet).

3. **No new repository method needed** — `as_of(symbol, at)` already exists in R5.

### Frontend

4. **`/research/[symbol]/+page.svelte`** — add `asOf` state (`null` = latest mode) + a `<input type="datetime-local">` + Apply button above `FactTimeline`. On apply, the page refetches `/api/v1/research/facts/{symbol}?as_of=<iso>` via client-side `fetch` and updates a reactive `currentFacts` state. The initial load uses `data.facts` (server-side, latest mode).

5. **Visual indicator on `FactTimeline`** — new optional `asOf?: string | null` prop. When non-null, the header reads "Recent facts (as of {iso})" instead of "Recent facts". Otherwise unchanged.

6. **Mock-fastapi**: extend `/facts/:symbol` to honour `?as_of=` (returns same 2-row payload, only adds an `as_of_echo` field for assertion).

### Tests

7. **Backend unit test** — extend the existing R5 facts test (or add a new one) that seeds 3 facts at staggered `recorded_from` timestamps and verifies `as_of` filters correctly.
8. **Vitest unit** for the new client-side as-of fetch helper (kept as a small typed function).
9. **Playwright e2e** — extend `research-brief-detail.spec.ts` to assert the as-of input appears + accepts a value (full flow test of the refetch is overkill for this slice).

## Out of scope

- **Per-fact effective-from picker** (separate axis) — current scope is `recorded_from` semantics ("what did we know at time X"). Combined effective + recorded picker is a v2 enhancement.
- **URL-state persistence** of `asOf` (deep-linking) — keep state client-only for now; saving to URL is a small follow-up.
