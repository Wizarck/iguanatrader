# Retrospective: risk-stoploss-guard

- **PR**: [#161](https://github.com/Wizarck/iguanatrader/pull/161) (merged 2026-05-14, squash `a313f9e`).
- **Archive path**: `openspec/changes/archive/2026-05-14-risk-stoploss-guard/`
- **Lines shipped**: protection module + models extension + engine `_PROTECTIONS` chain entry + 5 unit tests.

## What worked

- **Pure-function protection pattern reused** — `evaluate(proposal, state, caps) -> Decision` mirrors the existing 5 protections. `_PROTECTIONS` chain extended to 6. Composition-over-inheritance for the win.
- **Default-disabled via `threshold=None`** — operators opt in by setting `stoploss_guard_threshold` in `RiskCaps`; no behavioural change for unconfigured tenants. Same pattern Bollinger used for `squeeze_threshold`.
- **5 unit tests cover the boundary** — disabled (None), below threshold, at threshold (boundary), above threshold, zero-lookback defence.
- **Agent flagged service-layer prerequisite** — `Trade.exit_reason` column doesn't yet exist; protection is inert by construction (`RiskState.recent_stoploss_count_trailing` defaults to 0) until the daemon's RiskState builder lands the exit-reason classification. Clean separation of concerns.

## What didn't

- **Agent flagged pre-existing test failure** — `test_service_bus_bridge.py::test_bridge_publishes_proposal_risk_evaluated_on_allow` fails on bare main HEAD, unrelated to this slice. Pre-flag: another candidate for "pre-existing-Windows-flake-or-real-bug" investigation. Worth a `git stash` round-trip + Linux-CI cross-check to determine if it's another silent algorithmic bug like donchian-bounds was.

## Carry-forward

- **`Trade.exit_reason` column + classifier** — service-layer slice to populate `RiskState.recent_stoploss_count_trailing` from closed trades. Without this, the guard is inert. Slice `chore-add-exit-reason-column` is the prerequisite for the guard to actually fire.
- **`test_service_bus_bridge.py` failure investigation** — apply the lesson from fix-donchian: never accept "flake" without baseline check. Worth a separate `audit-bus-bridge-baseline` slice if it reproduces on Linux CI.
- **5th, 6th risk protections** (CooldownPeriod, TrailingStops) — next slices in the v1.5 risk extensions track.

## Pattern usage

- **Default-disabled-via-None-threshold** — third use of this pattern (Bollinger squeeze, RSI cross-up implicit, now StoplossGuard). Codify in playbook? Maybe v0.14.0.
- **State-derivation upstream, comparison-only in protection** — `RiskState.recent_stoploss_count_trailing` is built by the service layer (or daemon); the protection is a pure int comparison. Keeps protections trivially testable + behaviourally orthogonal.
- **Inert-by-construction safety** — when a feature requires upstream wiring not yet shipped, design it to be inert (return `allow` decisively) rather than throwing or asserting. Forward-compatible.
