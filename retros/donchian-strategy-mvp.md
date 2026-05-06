# Retrospective: donchian-strategy-mvp (T3)

- **Archived**: 2026-05-06
- **PR**: [#91](https://github.com/Wizarck/iguanatrader/pull/91)
- **Archive path**: `openspec/changes/archive/2026-05-06-donchian-strategy-mvp/`
- **Lines shipped**: ~700 LoC (5 src + 3 test files including a Hypothesis property test).

## What worked

- **No-lookahead invariant enforced at the abstract base** — the `Strategy.evaluate` wrapper slices `bars[:-1]` before delegating to the subclass `_compute_signal_impl`. Subclasses literally cannot peek at the future, no matter how badly they try. NFR-R5 is structurally guaranteed; the property test (Hypothesis-driven) certifies on every CI run for every strategy in the registry.
- **`STRATEGY_REGISTRY` dispatch table + manager cache eviction on version bump** — adding a new strategy is one new module + one line in the registry. Hot-reload (FR4) on `StrategyConfig.version` change is automatic via cache invalidation.
- **Wilder ATR + Decimal arithmetic** for the Donchian sizing path keeps the strategy mathematically correct (no float-rounding drift in the stop-distance computation that drives position size).
- **`itertools.pairwise` + `Decimal`-only type narrowing** caught by ruff RUF007 + RUF005 on first lint pass — minor cleanup, but cleaner code.

## What didn't

- **The `MIN_BARS` class attribute as `@property`** required a `# type: ignore[override]` because mypy doesn't accept overriding a class attribute with a property cleanly. Acceptable workaround, but the pattern is awkward — future strategies will copy-paste the type-ignore.
- **No backtest harness** — strategy correctness is exercised only via unit tests. A future `backtest-harness` slice with `HistoricalBarPort` + replay engine is needed to validate strategy behaviour against historical data with the same rigor as the no-lookahead invariant.
- **Property test in mid-coverage zone** — the Hypothesis test parametrises across `STRATEGY_REGISTRY` + generates random bar sequences but checks consistency between two prefixes (truncated vs extended at the same logical "now"). Subtle: it certifies the wrapper invariant, not the implementation invariant. A stronger test would assert the same proposal across multiple strategy instantiations with different prefix lengths.

## Lessons

- **Abstract base class pattern is the right enforcement mechanism for no-lookahead**. Future strategy domains (e.g. crypto, FX, options) inherit the invariant by construction. Compare to slice-2's `HeartbeatMixin` pattern — both demonstrate the value of "frame the invariant at the framework, not the implementation".
- **Property tests have low cost-per-strategy**. Adding a 6th strategy to `STRATEGY_REGISTRY` immediately adds Hypothesis coverage of its no-lookahead invariant for free — no additional test code needed.

## Carry-forward to next change

- **`backtest-harness` slice** (out of MVP scope but obvious next): `HistoricalBarPort` Protocol + replay engine + property test on backtest determinism.
- **Additional strategies**: Bollinger / RSI / MACD / VWAP — each is one new module + STRATEGY_REGISTRY entry.
- **T4 (trading-routes-and-daemon)**: wires `StrategyManager.evaluate_all` into the propose→risk→approve→execute pipeline.
- **`Strategy.MIN_BARS` `@property` typing workaround** — a follow-up slice could refactor `MIN_BARS` to a class method or `ClassVar[int]` to remove the type-ignore.
