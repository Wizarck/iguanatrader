# Retrospective: property-tests-bus-bridge-handlers

> **Forward-authored** — fill at archive with squash SHA, CI rounds, and pre-flag candidates.

- **PR**: TBD (merged TBD, squash `TBD`).
- **Archive path**: `openspec/changes/archive/2026-05-11-property-tests-bus-bridge-handlers/`
- **Lines shipped**: TBD insertions across 2 test files + openspec/retro. CI TBD.

## What worked

- TBD

## What didn't

- TBD

## Carry-forward

- **Property tests for the 3 outbound bridges** in `ApprovalService` (`_bridge_to_trading_{approved,rejected,timeout}_handler`) — analogous shape, deliberately deferred to keep this slice scoped. Could be a follow-up `property-tests-approval-outbound-bridges`.
- **Stateful Hypothesis tests** (multi-tick sequences) — v2 backtest-engine slice.

## Pattern usage

- 3rd `tests/property/` file authored using the canonical async-property-test shape: sync `def test_...` wrapping `async def _run(): ...; asyncio.run(_run())`. Codifies the pattern documented in #112 + #114 retros.
