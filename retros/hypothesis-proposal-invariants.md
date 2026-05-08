# Retrospective: hypothesis-proposal-invariants

> **Forward-authored**.

- **PR**: [#110](https://github.com/Wizarck/iguanatrader/pull/110) (merged 2026-05-08, squash `33067a3`).
- **Archive path**: `openspec/changes/archive/2026-05-08-hypothesis-proposal-invariants/`
- **Lines shipped**: 283 insertions across 4 files. CI 14/14 verde al primer push.

## What worked

- Extends the existing `tests/property/` pattern (sibling to `test_strategy_no_lookahead.py` + `test_risk_caps_invariant.py`).
- CI-blocking marker (`@pytest.mark.ci_blocking`) so a future strategy regression breaks the build immediately.
- Parametrized over `STRATEGY_REGISTRY` so new strategies inherit the invariants by construction (no manual test updates needed when strategies are added).
- Hypothesis catches edge cases (price spikes, sparse histories) that fixed-input unit tests would miss.

## What didn't

- `max_examples=50` is conservative (vs 200 in `test_risk_caps_invariant.py`) — runtime trade-off. Donchian/SMA strategies on 60-120 random closes are slow-ish (LRU cache resets per example). Can be dialled up later if a regression slips through with low-frequency triggers.

## Carry-forward

- **Stateful Hypothesis tests**: a sequence of bar-tick → strategy-evaluate calls (model multi-tick state). Out of scope for v1; v2 backtest-engine slice.
- **Strategy-specific edge cases** (ATR=0, all-flat history, zero-volume bars): covered by per-strategy unit tests in `tests/unit/contexts/trading/strategies/`.
- **Property tests for `TradingService.propose`**: emits exactly one `ProposalCreated` per non-None proposal; emits zero events when None. Could be added to test_service_orchestration.py as a property test.
