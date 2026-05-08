# Retrospective: donchian-strategy-mvp (slice T3)

- **Archived**: 2026-05-08 (post-hoc; PR merged 2026-05-06)
- **PR**: [#91](https://github.com/Wizarck/iguanatrader/pull/91)
- **Squash SHA**: `d377e16`
- **Archive path**: `openspec/changes/archive/2026-05-06-donchian-strategy-mvp/`
- **Schema**: spec-driven
- **Tasks**: 100% (Donchian-ATR + SMA-cross + StrategyManager + no-lookahead invariant + property tests)

## What worked

- **No-lookahead invariant enforced at the abstract base class** (`Strategy.compute_signal(bars)` → `bars[:-1]` → `_compute_signal_impl(history)`). Subclasses physically cannot peek at the current bar. Hypothesis property test (`tests/property/test_strategy_no_lookahead.py`) certifies the guarantee per CI run for every strategy.
- **Manager + version-bump cache invalidation** lets a `StrategyConfig.version` UPDATE invalidate cached instances without restart (FR4 hot-reload).
- **Two-strategy launch** (Donchian-ATR + SMA-cross) proved the manager handles >1 strategy per tenant without coupling to either one's specifics.
- **ATR-based position sizing** keeps quantity proportional to volatility — no fixed-quantity bugs that would punish small-cap trades.

## What didn't

- **Post-hoc archive only** (same silent-drift pattern as T2 + others; addressed by ai-playbook v0.10.2 propagate-archive workflow).
- **`StrategyConfigRepository.get_by_id`** was deferred to T4-followup-market-data — T3 shipped the strategy + manager but not the production session-scoped lookup. T4-followup §2.10 closed it.

## Lessons

- **Invariant-at-base-class** is the canonical pattern for class-of-bug elimination (vs. lint or per-strategy assertions). Lookahead bugs are gone forever in the inheritance tree.
- **Hypothesis property tests** for invariants are higher-leverage than unit tests for known cases — they regenerate the bug on every CI run with new random seeds.

## Carry-forward (closed downstream)

- ✅ T4-followup-market-data wired `_make_strategy_resolver` to `StrategyConfigRepository.get_by_id` + `manager._get_or_build`. Async signature change documented in T4-followup retro.
- ✅ T4-followup-market-data integration test (`test_trading_pipeline_e2e.py`) exercises Donchian end-to-end via synthetic uptrend + the full bus chain.
- (Future) Hypothesis property tests for proposal-shape invariants (item #6 in the v1.0 backlog plan) — extends the no-lookahead pattern to other safety-critical invariants.
