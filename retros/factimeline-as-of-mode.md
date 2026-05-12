# Retrospective: factimeline-as-of-mode

> **Forward-authored** — fill at archive.

- **PR**: [#119](https://github.com/Wizarck/iguanatrader/pull/119) (merged 2026-05-12, squash `a9fe0cd`).
- **Archive path**: `openspec/changes/archive/2026-05-12-factimeline-as-of-mode/`
- **Lines shipped**: 242 insertions / 9 deletions across 7 files. CI 12/12 verde tras 1 fix round (end-of-file-fixer pre-commit hook caught missing trailing newline on retro).

## What worked

- **R5's `repository.as_of(symbol, at)` already implemented the bitemporal predicate** — this slice was pure HTTP plumbing + frontend state. Total backend cost: 8 LoC of route handler delta. Proof that the early-bitemporal-schema investment compounds when the wiring finally lands.
- **Server-side initial load + client-side override** pattern: page renders with `data.facts` (SSR, latest mode) on first paint; `applyAsOf` swaps in `asOfFacts` reactively via `$derived((asOfFacts ?? data.facts) as FactRow[])`. Fast first paint, ergonomic interactive narrowing, no SvelteKit `invalidate(...)` round-trip needed.
- **Naive datetime → UTC coercion** in the route mirrors the canonical project convention (`shared.time.now()` returns UTC). Operators can paste `2026-05-01T00:00:00` without worrying about timezone suffixes.

## What didn't

- **End-of-file-fixer pre-commit hook** caught a missing trailing newline on `retros/factimeline-as-of-mode.md` after CI ran. The local lint pass (ruff + black + svelte-check) doesn't run the pre-commit hooks, so this kind of issue only surfaces in CI. Pre-flag candidate: when authoring new markdown files, end with `\n` (vim/sublime do this by default; some editors strip it). Trivial 1-byte fix but a CI round burned.

## Carry-forward

- **URL-state persistence** of `asOf` (deep-linking) — currently client-only state; saving to URL query param would let operators bookmark + share as-of views. Small follow-up.
- **Combined effective + recorded picker** — current scope is recorded-time only ("what did we know at time X"). Effective-time axis would answer "what was true in the world at time X" independently. v2 enhancement.

## Pattern usage

- **Server-side initial load + client-side override pattern**: page renders with `data.facts` (SSR, latest mode) on first load; `applyAsOf` does a client-only refetch that swaps in `asOfFacts` reactively. Operators get fast first paint + ergonomic interactive narrowing without a SvelteKit invalidate/round-trip.
- **Backend-already-has-the-method, just expose it** burndown: R5 shipped `repository.as_of(symbol, at)` but no HTTP surface invoked it. This slice is a pure plumbing job — proof that the bitemporal schema's value compounds once the wiring lands.

## Carry-forward

- **URL-state persistence** of `asOf` (deep-linking) — currently client-only state; saving to URL query param would let operators bookmark + share. Small follow-up.
- **Combined effective + recorded picker** — current scope is recorded-time only ("what did we know at time X"). Effective-time axis would answer "what was true in the world at time X" independently. v2 enhancement.

## Pattern usage

- **Server-side initial load + client-side override pattern**: page renders with `data.facts` (SSR, latest mode) on first load; `applyAsOf` does a client-only refetch that swaps in `asOfFacts` reactively. Operators get fast first paint + ergonomic interactive narrowing without a SvelteKit invalidate/round-trip.
- **Backend-already-has-the-method, just expose it** burndown: R5 shipped `repository.as_of(symbol, at)` but no HTTP surface invoked it. This slice is a pure plumbing job — proof that the bitemporal schema's value compounds once the wiring lands.
