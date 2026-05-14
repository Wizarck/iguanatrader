# Proposal: risk-cooldown-period

> **Add v1.5 `cooldown_period` risk protection** — rejects new proposals for a symbol within N seconds of the last closed trade on that symbol. Freqtrade `CooldownPeriod` pattern. Prevents revenge-trading and overtrading symptomatic of stop-and-reopen loops.

## Why

`docs/backlog.md` v1.5 §Risk engine extensiones lists "CooldownPeriod (tiempo mínimo entre trades del mismo symbol)". Common retail-trading anti-pattern: stopout fires → human (or signal) re-enters within minutes assuming "the noise is over" → second stopout fires. CooldownPeriod imposes a configurable wait, forcing a re-evaluation window. Per-symbol: a 30-min cooldown on TSLA doesn't block AAPL signals.

State input: `state.last_trade_closed_at_by_symbol: dict[str, datetime]` populated by the service layer from the most recent closed trade per symbol. Protection checks `now - last_closed_at[symbol] < cooldown_seconds`.

**But pure protection cannot read `now`.** Per the engine's PURITY PROHIBITED IMPORTS, `datetime.now()` is banned in protections. Solution: service layer pre-computes `seconds_since_last_close_by_symbol: dict[str, int]` at state-build time (one clock read, done once). The protection compares the int — no clock access.

## What

### New protection module

`apps/api/src/iguanatrader/contexts/risk/protections/cooldown_period.py`:

```python
def evaluate(
    proposal: TradeProposalInput,
    state: RiskState,
    caps: RiskCaps,
) -> Decision:
    if caps.cooldown_seconds is None:
        return Decision(outcome="allow")
    seconds_since_close = state.seconds_since_last_close_by_symbol.get(proposal.symbol)
    if seconds_since_close is None:
        return Decision(outcome="allow")  # no prior close → no cooldown
    if seconds_since_close < caps.cooldown_seconds:
        return Decision(
            outcome="reject",
            cap_type_breached="cooldown_period",
            current_pct=Decimal(seconds_since_close) / Decimal(caps.cooldown_seconds),
        )
    return Decision(outcome="allow")
```

### `RiskCaps` extension

- `cooldown_seconds: int | None = None` — minimum wait after a closed trade before a new one on the same symbol is allowed (None = disabled).

### `RiskState` extension

- `seconds_since_last_close_by_symbol: dict[str, int] = {}` — populated by service layer; key = symbol, value = `int((now - closed_at).total_seconds())`.

### Service-layer state derivation

`apps/api/src/iguanatrader/contexts/risk/service.py::_build_state`:
- Single SELECT: `SELECT symbol, MAX(closed_at) FROM trades WHERE tenant_id = ? AND state = "closed" GROUP BY symbol`.
- One `datetime.now()` call (the only clock read; per design D5 this is acceptable at service-layer scope).
- Compute `(now - closed_at).total_seconds()` for each row → fill `seconds_since_last_close_by_symbol`.
- Pass into `RiskState`.

### Engine composition wiring

`engine.py::_PROTECTIONS` — append `cooldown_period.evaluate` after `stoploss_guard` (or `max_drawdown` if stoploss_guard hasn't shipped yet — proposal proposes 7th slot post-stoploss-guard).

### Tests

`apps/api/tests/unit/contexts/risk/protections/test_cooldown_period.py`:

1. `test_cooldown_disabled_when_caps_seconds_none` → allow.
2. `test_cooldown_allows_when_no_prior_close_for_symbol` → allow.
3. `test_cooldown_rejects_within_window` (proposal.symbol="SPY", state.seconds_since[SPY]=300, caps.cooldown=1800) → reject.
4. `test_cooldown_allows_after_window_elapsed` (state.seconds_since[SPY]=2000, caps.cooldown=1800) → allow.
5. `test_cooldown_per_symbol_isolation` — state has SPY in cooldown but proposal.symbol="QQQ" → allow.

Service-layer integration:

6. `test_risk_state_computes_seconds_since_last_close_per_symbol` — seed 2 closed trades (SPY @ -10 min, QQQ @ -5 min), verify dict values.

## Out of scope

- **Per-strategy cooldown** — current is per-symbol; per-symbol-per-strategy (e.g., "MSFT-rsi has 30min cooldown, MSFT-donchian has 0") is v2.
- **Cooldown bypass via `/override`** — uses existing override mechanism, no new command.
- **Closed-trade direction sensitivity** — current implementation treats all closes equally. "Only impose cooldown on stop-loss closes, not target-hit closes" is a v1.5.x refinement.

## Acceptance

- `_PROTECTIONS` length = 7 (or 6 if stoploss_guard hasn't shipped — the protection is appendable in either order; the composition is independent).
- 5 new unit tests pass.
- 1 new integration test passes.
- `test_engine_purity.py` passes (no clock import in new protection module).
- mypy --strict clean.
- ruff + black clean.
