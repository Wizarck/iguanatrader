# Retrospective: factimeline-as-of-mode

> **Forward-authored** — fill at archive.

- **PR**: TBD (merged TBD, squash `TBD`).
- **Archive path**: `openspec/changes/archive/2026-05-12-factimeline-as-of-mode/`
- **Lines shipped**: TBD insertions / TBD deletions across TBD files. CI TBD.

## What worked

- TBD

## What didn't

- TBD

## Carry-forward

- **URL-state persistence** of `asOf` (deep-linking) — currently client-only state; saving to URL query param would let operators bookmark + share. Small follow-up.
- **Combined effective + recorded picker** — current scope is recorded-time only ("what did we know at time X"). Effective-time axis would answer "what was true in the world at time X" independently. v2 enhancement.

## Pattern usage

- **Server-side initial load + client-side override pattern**: page renders with `data.facts` (SSR, latest mode) on first load; `applyAsOf` does a client-only refetch that swaps in `asOfFacts` reactively. Operators get fast first paint + ergonomic interactive narrowing without a SvelteKit invalidate/round-trip.
- **Backend-already-has-the-method, just expose it** burndown: R5 shipped `repository.as_of(symbol, at)` but no HTTP surface invoked it. This slice is a pure plumbing job — proof that the bitemporal schema's value compounds once the wiring lands.
