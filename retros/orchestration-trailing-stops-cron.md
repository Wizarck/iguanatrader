# Retrospective: orchestration-trailing-stops-cron

- **PR**: [#168](https://github.com/Wizarck/iguanatrader/pull/168) (merged 2026-05-15, squash `dd66da4`).
- **Archive path**: `openspec/changes/archive/2026-05-15-orchestration-trailing-stops-cron/`
- **Lines shipped**: 1,195 insertions across 6 files (migration + ORM + repo + sweep service + cron wire + integration tests).

## What worked

- **Audit-only persist** — only `reason='trailed'` rows hit the DB. The math (N open trades × 4 sweeps/hr × 8 hr × 250 days ≈ 8K evals/yr/trade if we persisted everything vs ~10-50 ratchets/yr/trade in practice) drove a 2-order-of-magnitude write-volume reduction without losing observability — `no_update` / `trigger_not_reached` log at INFO.
- **Audit table as stop-history lookup** — no `Trade.current_stop_price` column was added. The audit table is the source of truth for stop drift; the resolver reads "latest audit row → else proposal stop". Keeps `Trade` write-once beyond its existing whitelist. Means broker-side reconciliation in the IBKR slice can just read `latest_audit_row.new_stop` to know what to CANCEL+REPLACE on the broker.
- **Inert-by-config via cap, not via registration** — the cron job registers unconditionally; the `trail_trigger_pct is None` short-circuit lives inside `sweep()`. Operators can flip the cap without a daemon restart. 4th use of the default-disabled-via-None pattern.
- **Per-trade exception isolation** — one bad symbol counts as `trades_skipped_no_bars` with type + symbol logged; the sweep continues. Critical for production: a single delisted ticker shouldn't abort all trailing.
- **Tenant scoping by listener** — zero `WHERE tenant_id = ?` in the new code. The slice-3 `tenant_listener` handles it. One explicit `test_sweep_is_tenant_scoped` proves cross-tenant isolation.
- **Manual execution beat the agent** — first attempt: agent died after 50 min with zero commits in its worktree (Step-0 worktree-isolation check or budget exhaustion, unclear). Killed it, took over manually, shipped end-to-end in ~30 min including debugging 4 latent gotchas. **Pre-flag**: when agents stall >30 min with no commits in their worktree, kill + take over is the right call.

## What didn't

- **4 sequential test-debug iterations** — each scenario surfaced a different latent issue:
  1. `trade_proposals.strategy_config_id` FK constraint — needed `_seed_strategy_config` helper (same bug also broke parent slice's tests; landed separately as PR #169).
  2. `RiskCaps` Pydantic forbids extras and my placeholder field names (`capital_pct_per_trade`, `daily_loss_cap_pct`) were stale guesses, not the actual K1 schema (`per_trade_pct`, `daily_loss_pct`).
  3. `Trade.entry_price_indicative` doesn't exist on `Trade` — entry price lives on `TradeProposal`. Required extending `_resolve_current_stop` to `_resolve_entry_and_stop` (returns tuple).
  4. SQLite `DateTime(timezone=True)` returns tz-naive on read despite the column declaration → pure function comparison `b.timestamp > trade.opened_at` raises TypeError. Same defensive coerce pattern used in `wire-risk-state-real-data`.
- **Test-flush-without-commit** — `add_row` flushed but never committed, so a sibling session reading audit rows saw zero. Fixed by adding explicit `session.commit()` at sweep-end when `trailed > 0`. Cron tick = transactional unit.
- **Both bus-bridge test files broken on main** — the parent slice (PR #166) shipped with 6/10 of `test_risk_repository_load_state.py` red because of the same FK issue I hit. CI is `--collect-only` so neither shipped slice noticed. The pattern is reproducible: **every integration test that touches `TradeProposal` needs `_seed_strategy_config` first**. Worth pinning to the playbook.

## Carry-forward

- **IBKR execution algos** (next slice in queue) — adds the broker-side CANCEL+REPLACE on stop ratchets + entry/exit-order placement with Market / TWAP / Adaptive. Activates the audit-row → broker-state write-through that this slice deliberately deferred.
- **`trades-close-flow-exit-classification`** — blocked on IBKR algos; without exit-order placement at the broker, `exit_reason` + `realised_pnl` stay NULL forever.
- **Equity-snapshot daemon** — drawdown still 0 in production until this lands. Independent of this slice but worth re-mentioning since it's the other half of the v1.5 protections finally firing.
- **CI pytest goes from `--collect-only` to real-run** — every slice this week has shipped with at least one latent test failure that CI couldn't catch. Cost is growing.

## Pattern usage

- **Audit-table-as-history-lookup (1st use)** — when a mutable state would re-open an append-only row's whitelist, use a dedicated audit table where the latest row IS the current state. Promote to playbook §append-only-state-via-audit if a second use lands.
- **Inert-by-config-cap (4th use)** — `default = None` on the trigger cap, short-circuit inside the service rather than at registration. Now codified across stoploss_guard, cooldown_period, bollinger squeeze, trailing-stops, and trailing-stop-sweep. Solidly playbook material.
- **Manual takeover after agent stall** — when worker-agent worktree shows zero commits >30 min after spawn, kill + take over rather than letting the budget burn. Saved ~50 min vs waiting for the (likely-stuck) agent to time out.
- **Skip-local-lints when worktree venv would hang** — used the main checkout's `.venv` directly via the project's installed `poetry run` from the main repo (root) rather than from a worktree. Worked first try, no 5-min venv-rebuild. The lint-hang root cause memory entry from earlier today is now applied in practice.
