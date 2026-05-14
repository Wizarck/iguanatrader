# Proposal: risk-stoploss-guard

> **Add v1.5 `stoploss_guard` risk protection** — rejects new proposals when the tenant has hit ≥N consecutive stoploss-triggered exits in the trailing M trades. Freqtrade `StoplossGuard` pattern, adapted to iguanatrader's pure-function protection composition. 6th protection in `_PROTECTIONS` chain after `per_trade → daily → weekly → max_open → max_drawdown`.

## Why

`docs/backlog.md` v1.5 §Risk engine extensiones lists "StoplossGuard (pause tras N stoploss consecutivos)" as the canonical "I'm in a losing-streak regime — stop the bleeding" filter. Daily/weekly loss caps trip on aggregate P&L but a tight consecutive-stop run (5 losers in a row, each just under the daily cap individually) can drain capital without ever tripping daily — StoplossGuard catches the regime change before the cap fires.

The guard is purely-functional + stateful: it reads `state.recent_stoploss_count_trailing` (an integer derived from the trailing M closed trades' exit-reason classification) and rejects when it crosses the configurable threshold. State derivation lives in the service layer (existing `RiskState` builder); the protection just compares the int.

## What

### New protection module

`apps/api/src/iguanatrader/contexts/risk/protections/stoploss_guard.py`:

```python
def evaluate(
    proposal: TradeProposalInput,
    state: RiskState,
    caps: RiskCaps,
) -> Decision:
    if caps.stoploss_guard_threshold is None:
        return Decision(outcome="allow")  # disabled by default
    if state.recent_stoploss_count_trailing >= caps.stoploss_guard_threshold:
        return Decision(
            outcome="reject",
            cap_type_breached="stoploss_guard",
            current_pct=Decimal(state.recent_stoploss_count_trailing) / Decimal(state.recent_trades_lookback),
        )
    return Decision(outcome="allow")
```

### `RiskCaps` model extension

`apps/api/src/iguanatrader/contexts/risk/models.py::RiskCaps` — add two optional fields:

- `stoploss_guard_threshold: int | None = None` — N stoploss exits required to trip (None = disabled).
- `stoploss_guard_lookback: int = 5` — M most-recent closed trades to consider.

### `RiskState` model extension

`RiskState` — add one field:

- `recent_stoploss_count_trailing: int = 0` — computed by the service layer's `_build_state(...)` function.
- `recent_trades_lookback: int = 0` — the M used to compute the count (denominator for `current_pct` reporting).

### Service-layer state derivation

`apps/api/src/iguanatrader/contexts/risk/service.py::_build_state` — query `trades` table:
- Filter: `tenant_id = ?`, `state = "closed"`, `exit_reason = "stop"` ORDER BY `closed_at DESC` LIMIT `caps.stoploss_guard_lookback`.
- Count rows where `exit_reason == "stop"` (vs target-hit / manual-close).
- Set `state.recent_stoploss_count_trailing` = that count.

If the trades table doesn't yet have `exit_reason` populated for all rows (legacy seed), default to 0 — the guard becomes inert until forward-fills classify exits.

### Engine composition wiring

`apps/api/src/iguanatrader/contexts/risk/engine.py::_PROTECTIONS` — add `stoploss_guard` after `max_drawdown`:

```python
_PROTECTIONS: tuple[ProtectionFn, ...] = (
    per_trade.evaluate,
    daily.evaluate,
    weekly.evaluate,
    max_open.evaluate,
    max_drawdown.evaluate,
    stoploss_guard.evaluate,  # NEW
)
```

### Tests

`apps/api/tests/unit/contexts/risk/protections/test_stoploss_guard.py`:

1. `test_stoploss_guard_disabled_when_threshold_none` — caps.stoploss_guard_threshold=None → always allow.
2. `test_stoploss_guard_allows_below_threshold` — count=2, threshold=3 → allow.
3. `test_stoploss_guard_rejects_at_threshold` — count=3, threshold=3 → reject with cap_type_breached="stoploss_guard".
4. `test_stoploss_guard_rejects_above_threshold` — count=5, threshold=3 → reject.

Plus a service-layer test in `tests/integration/test_risk_service.py`:

5. `test_risk_state_counts_recent_stoplosses` — seed 5 trades (3 with exit_reason="stop", 2 with exit_reason="target"), verify `state.recent_stoploss_count_trailing == 3`.

### Engine purity test

`tests/unit/contexts/risk/test_engine_purity.py` — already passes via AST scan; new protection module added to the scan automatically (the file is in the protections/ dir).

## Out of scope

- **Per-symbol StoplossGuard** — current implementation is portfolio-wide. Per-symbol variant (e.g., "pause MSFT after 3 stops on MSFT") is v2.
- **Exit-reason classification semantics** — assumes `exit_reason` field exists on Trade with values `"stop" | "target" | "manual" | "expiry"`. If migration `0014_exit_reason` doesn't already exist, prerequisite slice `chore-add-exit-reason-column` lands first.
- **Cooldown integration** — StoplossGuard is a halt; CooldownPeriod (separate v1.5 slice) is a temporal spacer. They compose independently.
- **Telegram `/override`** — operators can override the guard like any other cap via existing override mechanism. No new command needed.

## Acceptance

- `_PROTECTIONS` length = 6 (was 5).
- 4 new unit tests pass.
- 1 new integration test passes.
- `test_engine_purity.py` passes (no I/O in new module).
- mypy --strict clean.
- ruff + black clean.
