# Proposal: fix-donchian-channel-bounds

> **Fix `DonchianATRStrategy._compute_signal_impl` channel-high computation** — `window_highs` currently includes `bars[-1].high` in the lookback comparison, making the breakout condition `latest_close < channel_high` impossible to satisfy when the current bar's high is the window maximum (which is exactly when a breakout occurs). Surfaced 2026-05-14 in PR #157 agent report; reproduced locally on Windows venv with `test_donchian_emits_proposal_on_breakout` failing.

## Why

The Donchian channel-breakout signal is supposed to compare the CURRENT bar's close against the highest high of the N PRECEDING bars. The current implementation in `apps/api/src/iguanatrader/contexts/trading/strategies/donchian_atr.py:74`:

```python
window_highs = [bar.high for bar in bars[-lookback:]]
channel_high = max(window_highs)
```

includes `bars[-1].high` in the lookback window. Since by definition `bars[-1].high >= bars[-1].close` (high is the bar's max price; close ≤ high), `channel_high >= bars[-1].close` always. The breakout test on line 78 (`if latest_close < channel_high: return None`) therefore returns None on every breakout bar.

The bug went undetected because:
1. `.github/workflows/ci.yml` runs `pytest --collect-only` (not real execution); the failing test never surfaced server-side.
2. The original test `test_donchian_emits_proposal_on_breakout` failed silently — local pytest on a Windows venv catches it, but no agent or human ran the suite end-to-end on `main` for the slice's duration.

The bug is silent in production: every Donchian breakout signal is suppressed, so no DonchianATR trade ever fires regardless of operator configuration. The strategy has been shipped non-functional since slice T3.

## What

### Fix

`apps/api/src/iguanatrader/contexts/trading/strategies/donchian_atr.py:74` — change the slice from `bars[-lookback:]` to `bars[-lookback-1:-1]` (the N bars BEFORE the current one):

```python
# BEFORE
window_highs = [bar.high for bar in bars[-lookback:]]

# AFTER
window_highs = [bar.high for bar in bars[-lookback - 1 : -1]]
```

Update the inline docstring on line 73 to clarify: "Donchian channel: max of the prior `lookback` bars' high, EXCLUDING the current bar (we test whether the current close breaks the prior channel)".

### Test fix-up

`apps/api/tests/unit/contexts/trading/strategies/test_donchian_atr.py::test_donchian_emits_proposal_on_breakout` already tests the correct expected behaviour (proposal IS emitted on breakout). It currently fails — the fix makes it pass. The `extra_bar` trick the test uses (append a flat bar so the wrapper drops it and the ramp top becomes `bars[-1]` from `_compute_signal_impl`'s view) becomes redundant after the fix because the fix already excludes `bars[-1]`. Simplify:

```python
def test_donchian_emits_proposal_on_breakout() -> None:
    strategy = DonchianATRStrategy()
    history = _ramp_history()
    proposal = strategy.evaluate(symbol="AAPL", bars=history, config=_config())
    assert proposal is not None
    assert proposal.side == "buy"
    assert proposal.quantity > Decimal("0")
    assert proposal.stop_price < proposal.entry_price_indicative
```

The wrapper still slices `bars[:-1]`, so `_compute_signal_impl` sees bars 0-48 (49 bars). The new channel-high formula uses `bars[-21:-1]` = bars 28-47. Bar 47's high is at most 100.9 (since the ramp doesn't break out until bar 49 of the original). So `channel_high = max([bars 28..47].high) ≈ 100.9`. `latest_close = bars[-1].close = bars[48].close = 100 + 3*0.1 = 100.3` (the second-to-last bar of the ramp).

Wait — that means even after the fix, the test STILL fails because `bars[-1]` in `_compute_signal_impl`'s view is the SECOND-to-last bar of `_ramp_history()`, NOT the breakout bar. The ramp puts the breakout on bar n-1 (49), but the wrapper drops it.

Re-think: the test needs the ORIGINAL `_ramp_history()` (50 bars) to have its breakout on bar n-2 (48), so that after the wrapper drops bar 49, `bars[-1]` IS the breakout. Refactor `_ramp_history()` to put the spike on bar n-2:

```python
def _ramp_history(start_close: Decimal = Decimal("100"), n: int = 50) -> BarHistory:
    """Generate a synthetic price-ramp history that breaks out on bar n-2."""
    ...
    for i in range(n):
        if i == n - 2:    # spike at n-2, not n-1
            close = start_close + Decimal("10")
            high = close + Decimal("1")
            low = start_close
        else:
            ...
```

After wrapper truncation, `bars[-1]` = bar 48 = breakout bar. New channel-high formula `bars[-21:-1]` = bars 28-47, none of which include the spike. `channel_high ≈ 100.9`. `latest_close = 110`. Breakout fires.

Then add an explicit `test_donchian_no_signal_when_close_below_channel` regression test that verifies the old buggy semantics don't sneak back in (a flat ramp with no spike → no proposal).

### Acceptance

- `test_donchian_emits_proposal_on_breakout` PASSES (currently fails).
- All other tests in `test_donchian_atr.py` continue to pass.
- `test_strategy_no_lookahead.py` still passes (no logic change in `evaluate` wrapper).
- mypy --strict + ruff + black clean.

## Out of scope

- **Fixing CI to run real pytest instead of `--collect-only`** — separate carry-forward; gated on coverage reaching 80% (see project memory `ci-pytest-collect-only`).
- **Coverage push** — out of scope for this fix.
- **Symmetric short-side fix** — strategy is long-only in v1.5; sell-side comes with shorting support.
- **Per-symbol channel-high override (some symbols benefit from 50-bar lookback rather than 20)** — config-yaml concern, not a code fix.

## Estimate

Real diff: ~5 lines in `donchian_atr.py` (slice expression + 1-line docstring update) + ~10 lines in `test_donchian_atr.py` (move spike from n-1 to n-2 in the helper + drop the `extra_bar` hack + add 1 regression test).
