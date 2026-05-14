# Proposal: wire-risk-state-real-data

> **Replace `RiskRepository.load_risk_state`'s placeholder with real composed reads** — populates ALL state fields the v1.5 risk extensions added (`day_to_date_loss_pct`, `week_to_date_loss_pct`, `peak_to_trough_drawdown_pct`, `open_positions_count`, `recent_stoploss_count_trailing`, `recent_trades_lookback`, `seconds_since_last_close_by_symbol`) from `trades` + `equity_snapshots`. **Depends on `trades-add-exit-and-realised-pnl-columns` (prerequisite slice).** Makes the entire risk engine functional in production.

## Why

`apps/api/src/iguanatrader/contexts/risk/repository.py::RiskRepository.load_risk_state` currently returns `RiskState(capital=Decimal(0))` — explicit placeholder. All 7 risk protections (per_trade, daily_loss, weekly_loss, max_open, max_drawdown, stoploss_guard, cooldown_period) compose over this empty state in production: they evaluate but the state inputs are all defaults, so every cap appears under-utilised → engine always returns `allow`. Operators see a "green" risk dashboard regardless of actual P&L, drawdown, or stop history.

Memory `project_risk_state_placeholder` documents the failure mode in detail; this slice closes it.

## What

### Single composed read

`apps/api/src/iguanatrader/contexts/risk/repository.py::RiskRepository.load_risk_state`:

```python
async def load_risk_state(self, tenant_id: UUID) -> RiskState:
    """Composed read across trades + equity_snapshots + clock."""
    caps = await self._load_caps_for_tenant(tenant_id)  # for the lookback windows
    now = utc_now()
    today_utc = now.date()
    week_start = today_utc - timedelta(days=today_utc.weekday())

    # 1. Open positions count
    open_count = await self._count_open_trades(tenant_id)

    # 2. Equity snapshot — latest row in equity_snapshots
    latest_equity = await self._load_latest_equity(tenant_id)
    peak_equity = await self._load_peak_equity(tenant_id)

    capital = latest_equity or Decimal("10000")  # fallback to RiskCaps.default_equity if not yet wired
    drawdown_pct = (
        (peak_equity - latest_equity) / peak_equity
        if peak_equity and peak_equity > 0 and latest_equity is not None
        else Decimal(0)
    )

    # 3. Daily / weekly P&L (sum realised_pnl from trades closed in the window)
    day_pnl = await self._sum_realised_pnl_since(tenant_id, datetime.combine(today_utc, time.min, tzinfo=UTC))
    week_pnl = await self._sum_realised_pnl_since(tenant_id, datetime.combine(week_start, time.min, tzinfo=UTC))

    day_loss_pct = max(Decimal(0), -day_pnl / capital) if capital > 0 else Decimal(0)
    week_loss_pct = max(Decimal(0), -week_pnl / capital) if capital > 0 else Decimal(0)

    # 4. Stoploss-guard trailing
    recent_stop_count, recent_count = await self._count_recent_stoplosses(tenant_id, caps.stoploss_guard_lookback)

    # 5. Cooldown — seconds since last close per symbol
    seconds_since = await self._seconds_since_last_close_by_symbol(tenant_id, now)

    return RiskState(
        capital=capital,
        day_to_date_loss_pct=day_loss_pct,
        week_to_date_loss_pct=week_loss_pct,
        open_positions_count=open_count,
        peak_to_trough_drawdown_pct=drawdown_pct,
        recent_stoploss_count_trailing=recent_stop_count,
        recent_trades_lookback=recent_count,
        seconds_since_last_close_by_symbol=seconds_since,
    )
```

### Helper methods

Each helper is a single SQL query:

- `_count_open_trades(tenant_id)` → `SELECT COUNT(*) FROM trades WHERE tenant_id=? AND state='open'`
- `_load_latest_equity(tenant_id)` → `SELECT equity FROM equity_snapshots WHERE tenant_id=? ORDER BY recorded_at DESC LIMIT 1` (return None if no snapshots yet).
- `_load_peak_equity(tenant_id)` → `SELECT MAX(equity) FROM equity_snapshots WHERE tenant_id=?`. Same fallback.
- `_sum_realised_pnl_since(tenant_id, since)` → `SELECT COALESCE(SUM(realised_pnl), 0) FROM trades WHERE tenant_id=? AND state='closed' AND closed_at >= ? AND realised_pnl IS NOT NULL`. Returns Decimal.
- `_count_recent_stoplosses(tenant_id, lookback)` → `SELECT state, exit_reason FROM trades WHERE tenant_id=? AND state='closed' ORDER BY closed_at DESC LIMIT ?`. Iterate; count `exit_reason == 'stop'`. Return `(count, len_of_rows_returned)`.
- `_seconds_since_last_close_by_symbol(tenant_id, now)` → `SELECT symbol, MAX(closed_at) FROM trades WHERE tenant_id=? AND state='closed' GROUP BY symbol`. Dict comprehension over rows.

All queries scoped by tenant_id (defence in depth; the global tenant_listener also filters).

### Equity-snapshot fallback

If `equity_snapshots` is empty (early tenant, no daemon writes yet), `capital = Decimal("10000")` (matches `DEFAULT_EQUITY` in strategy modules). Drawdown stays at 0. This degrades cleanly until the equity daemon ships writes — operators see "no caps breached" rather than "engine crash".

### Tests

`apps/api/tests/integration/test_risk_repository_load_state.py`:

1. `test_empty_tenant_returns_fallback_state` — no trades, no equity → `capital=10000`, all pct = 0.
2. `test_open_trades_counted_correctly` — seed 3 open + 2 closed → `open_positions_count == 3`.
3. `test_latest_equity_picks_max_recorded_at` — seed 5 equity_snapshots; latest is the max `recorded_at`.
4. `test_peak_equity_picks_max_equity` — peak query returns max equity across history.
5. `test_drawdown_computed_from_peak_minus_latest` — peak=12000, latest=9000 → drawdown = 0.25.
6. `test_day_loss_pct_sums_today_only` — seed 2 trades closed today (-100, +50) + 1 yesterday (-200) → day_pnl = -50 → day_loss_pct = 50/capital.
7. `test_week_loss_pct_sums_since_monday` — seed trades across the week + last week → only this-week counted.
8. `test_recent_stoplosses_counts_exit_reason_stop` — seed 5 closed (3 stop, 1 target, 1 manual) → `recent_stoploss_count_trailing == 3`.
9. `test_seconds_since_last_close_per_symbol_dict` — seed 2 symbols (SPY @ -10 min, QQQ @ -5 min) → dict has both with tolerance.
10. `test_state_is_tenant_scoped` — seed 2 tenants with different data; assertions don't leak.

### Caveat: `equity_snapshots` daemon not wired here

This slice reads from `equity_snapshots` assuming the table exists (it does — slice O1 created it). The DAEMON that periodically writes equity snapshots is a separate concern (see `equity-snapshot-daemon` carry-forward in the project memory). Until that daemon runs, the table stays empty → drawdown reports 0. That's acceptable: the slice fails gracefully (no exception, just no drawdown enforcement). When the daemon ships, drawdown reporting activates without further code changes.

## Out of scope

- **Equity snapshot daemon** — separate slice; this proposal assumes empty `equity_snapshots` initially. Documented degradation: drawdown stays 0.
- **Wiring the close-flow to populate `exit_reason` + `realised_pnl`** — separate slice (`trades-close-flow-exit-classification`). Without that, the queries here return mostly NULL → conservative defaults.
- **Per-tenant cache** — `load_risk_state` is called once per evaluation. Caching is a v1.5.x perf concern; v1.5 keeps the explicit-fresh-read invariant.
- **Multi-currency normalisation** — sum assumes single quote currency. v1.5 ASIS uses operator's reported currency consistently.
- **`max_drawdown` enforcement against historical peak across tenants' lifetime** — current proposal uses `MAX(equity)` from `equity_snapshots`. Resetting the peak on capital injection (deposit) is a v2 concern.

## Acceptance

- `RiskRepository.load_risk_state` returns a fully-populated `RiskState` for any tenant.
- 10 integration tests pass.
- mypy --strict + ruff + black clean on touched files.
- `test_engine_purity.py` still passes (no changes to engine or protections; only repository layer).
- Existing risk-engine integration tests still pass (the engine continues to receive a valid `RiskState`).
- `project_risk_state_placeholder` memory archived (the gap is closed).

## Dependencies

- **HARD prerequisite**: `trades-add-exit-and-realised-pnl-columns` (adds the `exit_reason` + `realised_pnl` columns this slice reads). If the prerequisite hasn't merged, this slice cannot ship — surface as `blocked: needs trades-add-exit-and-realised-pnl-columns`.
- **Soft prerequisite**: equity-snapshot-daemon (for drawdown to actually reflect reality). Slice ships without it; drawdown stays 0 until daemon lands.
