# Proposal: orchestration-trailing-stops-cron

> **Wire `compute_trailing_stop` into the daemon cron.** PR #163 shipped the pure function; this slice adds the sweep job that fetches open trades + post-entry bars, calls the function per trade, and persists results to a new `trailing_stop_audit` table. Default-disabled via the existing `RiskCaps.trail_trigger_pct=None` cap.

## Why

`apps/api/src/iguanatrader/contexts/risk/stop_management.py::compute_trailing_stop` exists but has zero production callers (`grep` confirms — only tests reference it). Without this sweep, `trail_trigger_pct` configured by an operator does nothing. The retro for PR #163 explicitly carries this slice forward as the activation step.

## What

### New audit table (migration 0016)

`trailing_stop_audit` — one row per sweep evaluation per trade where `reason='trailed'` (i.e., we only persist when the stop actually ratcheted; `no_update` and `trigger_not_reached` are logged at INFO, not persisted, to avoid every-15-min × N-open-trades DB bloat).

```sql
CREATE TABLE trailing_stop_audit (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    trade_id UUID NOT NULL REFERENCES trades(id),
    swept_at TIMESTAMPTZ NOT NULL,
    old_stop NUMERIC(18, 8) NOT NULL,
    new_stop NUMERIC(18, 8) NOT NULL,
    highest_close_since_entry NUMERIC(18, 8) NOT NULL,
    atr NUMERIC(18, 8) NOT NULL,
    bars_evaluated INTEGER NOT NULL
);
CREATE INDEX ix_trailing_stop_audit_trade_id_swept_at
    ON trailing_stop_audit(trade_id, swept_at DESC);
CREATE INDEX ix_trailing_stop_audit_tenant_id
    ON trailing_stop_audit(tenant_id);
```

Table is fully append-only (`__tablename_is_append_only__ = True`, empty whitelist) — the audit row is the historical record; you do not update prior sweeps.

### Current-stop resolution

The pure function needs the trade's CURRENT stop as input. There is no `trades.stop_price` column. Resolution order in `TradingRepository.get_current_stop(trade_id)`:

1. Latest `trailing_stop_audit.new_stop` for `trade_id` ordered by `swept_at DESC` (if any audit row exists — the most-recent ratchet wins).
2. Else `TradeProposal.stop_price` joined via `Trade.proposal_id` (the entry-time stop set at proposal evaluation).

This keeps `Trade` immutable beyond its existing whitelist; the audit table IS the stop history.

### Sweep service

`apps/api/src/iguanatrader/contexts/risk/trailing_stop_sweep.py`:

```python
@dataclass(frozen=True, slots=True)
class TrailingStopSweepResult:
    trades_evaluated: int
    trades_trailed: int
    trades_no_update: int
    trades_trigger_not_reached: int
    trades_skipped_no_bars: int
    duration_ms: int


class TrailingStopSweepService:
    def __init__(
        self,
        *,
        trading_repo: TradingRepository,
        risk_caps_provider: Callable[[], RiskCaps],
        market_data_port: MarketDataPort,
        clock: Callable[[], datetime] = utc_now,
    ) -> None: ...

    async def sweep(self) -> TrailingStopSweepResult:
        caps = self._risk_caps_provider()
        if caps.trail_trigger_pct is None:
            # Default-disabled: no caps configured.
            return TrailingStopSweepResult(0, 0, 0, 0, 0, duration_ms=0)
        trades = await self._trading_repo.list_open_for_tenant()
        ...  # per-trade loop
```

Per-trade loop:
1. Fetch `current_stop` via the resolution order above.
2. Fetch post-entry bars from `market_data_port.get_bars(symbol, timeframe='1d', lookback_bars=200)`; filter `bar.timestamp > trade.opened_at`.
3. Call `compute_trailing_stop(trade=TradeSnapshot(...), bars=bars, ...caps...)`.
4. On `reason='trailed'`: INSERT into `trailing_stop_audit`. Log at INFO.
5. On `no_update` / `trigger_not_reached`: log at DEBUG. No DB write.
6. Increment the appropriate counter.

Per-trade failures (broker fetch error, missing bars, etc.) are logged + skipped (`trades_skipped_no_bars` counter); the sweep continues. One bad symbol does not abort the whole sweep.

### Cron wiring

`OrchestrationService.bootstrap_routines` gains a 6th `JobSpec`:

```python
JobSpec(
    name="trailing_stops_sweep",
    fn=_sweep_fn,
    cron_kwargs={"hour": "9-16", "minute": "*/15", "day_of_week": "mon-fri"},
)
```

Every 15 minutes during US market hours (matches the daemon's existing market-hours convention). The job is registered unconditionally; default-disabled gating happens INSIDE `sweep()` via the `trail_trigger_pct is None` check (consistent with the inert-by-construction pattern).

Backwards-compat: the new `trailing_stop_sweep_service` param to `bootstrap_routines` is Optional. If `None`, the cron is not registered (older test setups that don't wire trailing stops still pass).

## Why this shape

- **Audit table over `trades.stop_price` column** — keeps `Trade` write-once beyond its existing whitelist (state, closed_at, exit_reason, realised_pnl). The audit table is the source of truth for stop history; broker-side reconciliation (CANCEL+REPLACE on IBKR) reads the latest audit row in a future slice. Avoids re-opening the `Trade` whitelist for a column that will be UPDATEd often.
- **Default-disabled via cap, not via registration** — registering the job unconditionally and short-circuiting inside `sweep()` keeps the registration pure (no caps-dependent control flow in bootstrap), matches the inert-by-construction pattern used 4× elsewhere in the codebase, and lets operators enable trailing without a daemon restart.
- **Only `trailed` rows persisted** — N open trades × 4 sweeps/hr × 8 hr × 250 trading days = ~8K writes/year per trade if we persisted every evaluation. Persisting only ratchets reduces to ~10–50 writes/year per trade (the realistic frequency of new highs on a long-running winner). DEBUG logs cover the no-op cases.
- **15-min cadence** — matches the existing market-hours daemon convention. Tighter cadence (1-min) doesn't help: trailing reacts to new bar closes, and the project's `timeframe='1d'` strategies close once per day. A future 1H/15m strategy slice would tighten the cadence accordingly.
- **No broker integration in this slice** — persisting the new stop in the audit table is the slice's job; CANCEL+REPLACE on IBKR is part of the IBKR execution algos slice. Until that lands, the audit table is informational; the broker's stop order still sits at the entry-time price. Documented as out-of-scope.

## Out of scope

- Broker-side stop reconciliation (CANCEL + REPLACE on IBKR). Bundled into the IBKR execution algos slice.
- Short-side trailing (v2; v1.5 is long-only, the pure function short-circuits sells).
- 1m/15m cadence for sub-daily strategies. Future slice when a sub-daily strategy ships.
- Backfill of audit rows for trades open before this slice merges (they will get audited on the first post-merge sweep that finds a new high).

## Tests

Integration tests in `apps/api/tests/integration/test_trailing_stop_sweep.py`:

1. `test_sweep_short_circuits_when_trail_trigger_pct_is_none` — caps with `None` trigger → result is all-zeros, no DB writes.
2. `test_sweep_zero_open_trades_returns_zero_evaluated` — empty `trades` table → clean result.
3. `test_sweep_persists_audit_row_on_trailed` — open long with favorable move + ATR distance → audit row inserted with correct fields.
4. `test_sweep_no_audit_row_on_no_update` — open long with pullback after prior ratchet → DEBUG log only, no new audit row.
5. `test_sweep_no_audit_row_on_trigger_not_reached` — new trade, no favorable move yet → no audit row.
6. `test_sweep_resolves_current_stop_from_latest_audit_row` — trade with prior `trailing_stop_audit` row → second sweep uses that as `current_stop` (not the proposal's entry-time stop).
7. `test_sweep_resolves_current_stop_from_proposal_when_no_audit` — first sweep for a trade → uses `TradeProposal.stop_price`.
8. `test_sweep_skips_short_trades` — sell-side trade → no audit row (pure function short-circuits).
9. `test_sweep_continues_after_per_symbol_failure` — market_data_port raises for symbol X but not Y → Y is evaluated normally, X counted in `trades_skipped_no_bars`.
10. `test_sweep_is_tenant_scoped` — two tenants, each with one open trade → tenant A's sweep does not touch tenant B's audit table.

Unit tests for `_resolve_current_stop` helper (2 tests covering the two branches).
