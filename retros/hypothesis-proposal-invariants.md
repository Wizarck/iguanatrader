# Retrospective: hypothesis-proposal-invariants

> **Forward-authored**.

- **PR**: TBD
- **Archive path**: `openspec/changes/archive/<archive-date>-hypothesis-proposal-invariants/`
- **Lines shipped**: ~250 LoC (~210 test + ~40 retro/openspec).

## What worked

- _(fill on archive — pre-flag candidates: extends the existing tests/property/ pattern (test_strategy_no_lookahead.py + test_risk_caps_invariant.py); CI-blocking marker so future strategy regressions break the build; parametrized over STRATEGY_REGISTRY so new strategies inherit the invariants by construction.)_

## What didn't

- _(fill on archive — pre-flag candidates: max_examples=50 (vs 200 in test_risk_caps_invariant.py) tradeoff between coverage + CI runtime; can be dialled up later if a regression slips through.)_

## Carry-forward

- **Stateful Hypothesis tests**: a sequence of bar-tick → strategy-evaluate calls (model multi-tick state). Out of scope for v1; v2 backtest-engine slice.
- **Strategy-specific edge cases** (ATR=0, all-flat history, zero-volume bars): covered by per-strategy unit tests in `tests/unit/contexts/trading/strategies/`.
- **Property tests for `TradingService.propose`**: emits exactly one `ProposalCreated` per non-None proposal; emits zero events when None. Could be added to test_service_orchestration.py as a property test.
