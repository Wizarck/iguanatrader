# Proposal: hypothesis-proposal-invariants

> Adds Hypothesis property tests for `Proposal` shape invariants emitted by `StrategyPort.evaluate`. Companion to existing `tests/property/test_strategy_no_lookahead.py` (lookahead invariant) + `test_risk_caps_invariant.py` (risk caps). Test-only slice — zero runtime code changes.

## Why

T4 retro pre-flagged "Hypothesis property tests for proposal validation" as deferred. Currently:

- `Strategy.evaluate(...)` may return a `Proposal | None`.
- `Proposal` is a frozen dataclass with no `__post_init__` validation. The shape contract (quantity > 0, side ∈ {"buy","sell"}, stop_price relative to entry_price for buy/sell) is documented in `docs/architecture-decisions.md` + spec but NOT mechanically enforced.

Without property tests, a future strategy could accidentally emit a `Proposal(quantity=Decimal("-5"))` or `Proposal(side="bork")`, and downstream consumers (RiskService, BrokerPort) would either silently accept or fail at constraint-check time. A Hypothesis test that runs every registered strategy against random `BarHistory` inputs catches the class of bug at strategy-author time.

## What

Single new test file: `apps/api/tests/property/test_proposal_shape_invariants.py` — `@pytest.mark.property + @pytest.mark.ci_blocking`. ~150 LoC.

For every strategy in `STRATEGY_REGISTRY` × random `BarHistory` (Hypothesis-generated): IF `strategy.evaluate(...)` returns a non-None `Proposal`, THEN:

1. `proposal.quantity > 0`.
2. `proposal.side in {"buy", "sell"}`.
3. `proposal.entry_price_indicative > 0`.
4. `proposal.stop_price > 0`.
5. **Direction invariant**:
   - `side == "buy"` ⇒ `stop_price < entry_price_indicative` (a "buy" stop must be below the entry for a long position).
   - `side == "sell"` ⇒ `stop_price > entry_price_indicative` (a short stop must be above the entry).
6. `proposal.mode in {"paper", "live"}`.
7. `proposal.symbol == bars.symbol` (no cross-symbol contamination).
8. `proposal.tenant_id == config.tenant_id` (no cross-tenant contamination).

Plus 1 test for the `None` path:

9. If `strategy.evaluate(...) is None`, no further assertion — but the test confirms the call doesn't raise on randomly-generated bars.

## Out of scope

- Property tests for `RiskService.evaluate_proposal` — already covered by `test_risk_caps_invariant.py`.
- Property tests for the no-lookahead invariant — already covered by `test_strategy_no_lookahead.py`.
- Stateful Hypothesis tests (a sequence of bar-tick → strategy-evaluate calls) — out of scope; v2 backtest-engine slice.
- Strategy-specific edge cases (e.g. ATR=0 in DonchianATRStrategy) — covered by per-strategy unit tests.

## Acceptance criteria

1. `pytest apps/api/tests/property/test_proposal_shape_invariants.py` passes 200 examples per strategy.
2. The test is `@pytest.mark.ci_blocking` so a future regression breaks CI.
3. mypy --strict + ruff + black + pre-commit + CI green.

## Blast radius

ZERO runtime code. NEW test file only.

## Estimated effort

~2-3h, ~180 LoC (test file).
