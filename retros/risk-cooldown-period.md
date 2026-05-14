# Retrospective: risk-cooldown-period

- **PR**: [#162](https://github.com/Wizarck/iguanatrader/pull/162) (merged 2026-05-14, squash `e1ebc2e`).
- **Archive path**: `openspec/changes/archive/2026-05-14-risk-cooldown-period/`

## What worked

- **Per-symbol cooldown via `dict[str, int]`** — `RiskState.seconds_since_last_close_by_symbol` keyed by symbol; each symbol's cooldown is independent. Two simultaneous trades on different symbols can pass even if both symbols' cooldown windows overlap (different states).
- **Branch-exists pre-flight check from agent** — agent confirmed no parallel session before pushing, per the lesson from PR #159 retro.
- **Default-disabled pattern (3rd use)** — `cooldown_seconds: int | None = None`. Consistent with stoploss_guard + Bollinger. Worth promoting to playbook as a v1.5 patch.

## What didn't

- **`test_service_bus_bridge.py` failures STILL flagged** — both stoploss_guard + cooldown_period agents reported pre-existing failures on this test. NOT a regression from this slice. Investigation queued. Carry-forward: `audit-bus-bridge-baseline` slice.
- **`TradeProposalInput.symbol` defaulted to empty string** — agent flagged this as a "blast-radius minimization" workaround. The proper service-layer slice that wires the real symbol value is out of scope. The default keeps existing tests green; it makes cooldown_period inert when input doesn't carry a symbol. Inert-by-construction safety pattern.

## Carry-forward

- **Bus-bridge baseline failure investigation** — apply fix-donchian lesson: never accept "flake" without baseline check. Two independent agents flagged the same test; high probability of a real algorithmic bug similar to donchian-bounds.
- **`TradeProposalInput.symbol` real-value wiring** — service-layer slice to populate from the actual proposal. Until then, cooldown is inert.
- **TrailingStops** — 8th protection. Next slice in v1.5 risk track.

## Pattern usage

- **Default-disabled-via-None-threshold (3rd use)** — promote to playbook §risk-protections-canonical-pattern. The 3-use threshold is met.
- **Per-symbol scoping via `dict[str, T]`** — when state is naturally keyed by a domain entity (symbol, tenant, strategy), use `dict[K, V]` instead of "current_symbol + last_close_time" — keeps protection trivially testable + handles concurrent symbols.
- **Inert-by-construction safety (3rd use)** — stoploss_guard, cooldown_period, and `TradeProposalInput.symbol=""` all use the pattern. Codify in playbook.
