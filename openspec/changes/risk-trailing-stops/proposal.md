# Proposal: risk-trailing-stops

> **Add v1.5 dynamic trailing-stops** — when a long position moves favorably by `trail_trigger_pct`, ratchet the stop up to `(highest_close_since_entry - trail_atr_mult * ATR)`. NOT a pre-trade protection; a POST-FILL stop-adjustment service that runs each bar on open positions. Lives outside the pure-function `risk/protections/` pattern — under `risk/stop_management.py`.

## Why

`docs/backlog.md` v1.5 §Risk engine extensiones lists "Trailing stops dinámicos (custom_stoploss equivalent)". Without trailing, a winner that runs 10% before reversing gives back most of the gains because the static ATR-stop sits at entry-time levels. Trailing locks in profits dynamically: as the position moves up, the stop follows N×ATR below the local high. Standard retail-equity feature.

This is **not a pre-trade protection** — the existing risk engine is `(Proposal, State, Caps) → Decision` at proposal-evaluation time. Trailing operates on EXISTING positions each bar. Separate service.

## What

### New service module

`apps/api/src/iguanatrader/contexts/risk/stop_management.py`:

```python
@dataclass(frozen=True)
class TrailingStopUpdate:
    trade_id: UUID
    old_stop: Decimal
    new_stop: Decimal
    highest_close_since_entry: Decimal
    atr: Decimal
    reason: str  # "trailed" | "no_update" | "trigger_not_reached"


def compute_trailing_stop(
    *,
    trade: TradeSnapshot,                          # entry_price + current stop_price + side
    bars: BarHistory,                              # since entry
    trail_trigger_pct: Decimal,                    # e.g., 0.03 (3% favorable move triggers trailing)
    trail_atr_mult: Decimal,                       # e.g., 1.5
    atr_period: int = 14,
) -> TrailingStopUpdate:
    """Pure function. Returns the proposed new stop (or no_update marker).
    Does NOT mutate state; caller persists.
    """
    ...
```

Logic for long-side:
1. Compute `highest_close_since_entry = max(b.close for b in bars where b.ts > trade.opened_at)`.
2. Compute `favorable_pct = (highest_close_since_entry - trade.entry_price) / trade.entry_price`.
3. If `favorable_pct < trail_trigger_pct`: `TrailingStopUpdate(reason="trigger_not_reached", new_stop=trade.stop_price)`.
4. Compute `ATR(atr_period)` over the post-entry bars.
5. `candidate_stop = highest_close_since_entry - trail_atr_mult * ATR`.
6. If `candidate_stop > trade.stop_price`: return update with `reason="trailed"`.
7. Else: `reason="no_update"` (don't ratchet down — stops only go up for longs).

Sell-side (short): mirror with sign reversal. v1.5 still long-only by default; sell-side branch lives but is unexercised.

### Caller: a new cron routine or signal-handler

The proposal does NOT wire a caller. Wiring options:
- **A.** Add to existing `orchestration.service.py` cron routines (e.g., `trailing_stops_sweep` every 5 min during market hours).
- **B.** Hook into the bar-receive event handler — every new bar triggers a `compute_trailing_stop` pass for the symbol's open positions.

**Decision**: option A. Cron-driven. Simpler than event-handler hook; trailing-stop precision at 5-min granularity is sufficient for v1.5 (intraday precision is v1.5.x or v2).

The cron routine wiring is a SEPARATE follow-up slice (`orchestration-trailing-stops-cron`), not this slice. This slice ships the PURE function + the data type. The follow-up wires the cron.

### `RiskCaps` extension

- `trail_trigger_pct: Decimal | None = None` — favorable move threshold (None = trailing disabled).
- `trail_atr_mult: Decimal = Decimal("1.5")` — multiplier for the trailing distance.
- `trail_atr_period: int = 14`.

### Tests

`apps/api/tests/unit/contexts/risk/test_stop_management.py`:

1. `test_trailing_no_update_when_trigger_not_reached` — favorable_pct < trigger → reason="trigger_not_reached".
2. `test_trailing_ratchets_up_on_favorable_move` — engineered bars rising 5%, trigger=3% → reason="trailed", new_stop > old.
3. `test_trailing_does_not_ratchet_down_on_pullback` — new candidate < old stop → reason="no_update", new_stop == old.
4. `test_trailing_uses_post_entry_bars_only` — bars from before entry are ignored.
5. `test_trailing_long_only_v1_5` — short trade (side="sell") returns reason="trigger_not_reached" or similar safe default; explicit short-side test deferred to v2.
6. `test_trailing_atr_period_param_overridable` — `atr_period=20` instead of 14 changes the trailing distance.

## Out of scope

- **Cron wiring** — handled by separate `orchestration-trailing-stops-cron` follow-up slice.
- **Per-symbol trailing params** — config-yaml per-symbol overrides (TSLA tighter trail, SPY looser) are v1.5.x.
- **Sell-side short positions** — v2 alongside shorting.
- **Time-based trailing** — "trail wider in first hour after entry, then tighten" is v2.
- **Multi-level trailing** — "first move: trail at 2×ATR; second move: tighten to 1×ATR" is v2.

## Acceptance

- `risk/stop_management.py` exports `compute_trailing_stop` + `TrailingStopUpdate`.
- 6 new unit tests pass.
- mypy --strict clean (pure function; no I/O).
- ruff + black clean.
- `RiskCaps` model gains 3 new trailing-related fields with sensible defaults.
- Follow-up slice `orchestration-trailing-stops-cron` proposal queued (not implemented in this slice).
