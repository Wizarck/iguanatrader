# Retrospective: risk-trailing-stops

- **PR**: [#163](https://github.com/Wizarck/iguanatrader/pull/163) (merged 2026-05-15, squash `38b59fc`).
- **Archive path**: `openspec/changes/archive/2026-05-15-risk-trailing-stops/`
- **Agent wall-time**: 71 minutes (longest single-slice agent to date).

## What worked

- **Separate-service shape over `_PROTECTIONS` chain entry** — trailing-stops adjusts open-trade stops (not gates new proposals); proper module separation (`stop_management.py`) preserves the engine's pre-trade-only contract. Cron service (deferred slice) will call `compute_trailing_stop` per open trade.
- **8th risk facility shipped** — `RiskCaps` gains `trail_trigger_pct` + `trail_atr_mult` + `trail_atr_period`. Default-disabled (`trail_trigger_pct=None`) — 4th use of the pattern.
- **Long-only-safe boundary** — sell-side returns `trigger_not_reached` no-op so a future cron sweep can call blanket regardless of side; shorts simply skip.
- **ATR-undefined boundary explicit** — single-bar post-entry history → `no_update` rather than divide-by-zero or zero-distance stop.

## What didn't

- **Agent wall-time 71 minutes** — unusual. Likely due to either lint-iteration cycles OR test-running-on-slow-Windows-venv (the bus-bridge investigation showed unit tests there taking 21 min on a known-broken suite). No insight into root cause from the report. Pre-flag: when agent wall-time exceeds 15 min, file a follow-up `chore-agent-timing-audit` to understand what consumed time (lints, tests, retries).
- **Wilder ATR inlined as 4th copy** — agent deliberately did NOT use `_indicators.compute_atr` from the trading domain. Rationale: avoids risk→trading cross-import (architectural boundary preserved). Trade-off: 4th copy of a 14-line helper. Acceptable in DDD terms; the risk and trading modules are bounded contexts.

## Carry-forward

- **`orchestration-trailing-stops-cron`** — wire `compute_trailing_stop` into the daemon's per-tick or per-bar update loop. Without this, the function exists but never runs. Next slice in this thread.
- **Risk-only `_indicators.py`** — if a 2nd risk-domain caller needs ATR, hoist `compute_atr` to `apps/api/src/iguanatrader/contexts/risk/_indicators.py` (sibling of strategies' version). 4 copies across both contexts = 2 copies in each = manageable.
- **Agent timing audit** — 71-min wall-time is suspect; investigate.

## Pattern usage

- **Default-disabled-via-None (4th use)** — now codified across stoploss_guard, cooldown_period, bollinger squeeze, trailing_stops. Promote to playbook §risk-protection-defaults.
- **DDD boundary: copy over cross-context import** — when a helper exists in trading but is needed in risk, copying preserves bounded-context independence. Acceptable when the helper is small (<20 lines) and stable. Trade-offs documented.
- **Inert-by-construction (4th use)** — sell-side returns no-op; ATR-undefined returns no_update; missing-trigger-config returns no_update. Three independent inert paths in one module.
