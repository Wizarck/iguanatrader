# Retrospective: market-data-replay

> **Forward-authored**.

- **PR**: [#109](https://github.com/Wizarck/iguanatrader/pull/109) (merged 2026-05-08, squash `93eca65`).
- **Archive path**: `openspec/changes/archive/2026-05-08-market-data-replay/`
- **Lines shipped**: 745 insertions / 6 deletions across 9 files. CI 14/14 verde tras 1 round (round 1 mypy: ReplayResult dataclass needed mutable for bars_loaded accumulation; fixed by dropping frozen=True).

## What worked

- Optional `as_of` kwarg on `MarketDataPort.get_bars` keeps backwards-compatibility (existing daemon callers untouched).
- Replay service is fully read-only by construction (no MessageBus, no broker, no propose call).
- Reuses existing `_make_strategy_resolver` from `cli/trading.py` for strategy lookup — no duplication.
- CLI subcommand auto-discovered into existing `iguanatrader market-data` Typer app from T4-followup-market-data.

## What didn't

- `Proposal` dataclass has 11 fields incl. `confidence_score` + `mode` that I missed in the test fixture — caught at compile time. Pre-flag for future tests touching trading.ports types.
- `ReplayResult` initially declared `frozen=True` — `bars_loaded += len(...)` on a frozen dataclass raises at mypy --strict (`misc` error). Fix: drop `frozen=True` (kept `slots=True` for memory). Pre-flag: when accumulating across a loop, dataclass must be mutable.

## Carry-forward

- **Multi-day replay** (`--start-date / --end-date` looping) — operator scripts in shell for v1; native CLI loop is v2.
- **Persisted replay history** — stdout-only in v1; v2 SaaS slice can write to a `replay_history` table for ops dashboards.
- **Slippage / commission / equity simulation** — full backtest engine is a separate slice on the v1.5 backlog.
- **Proposal `reasoning` rendering**: cast to `str()` in v1 (dict serialisation); future improvement is a structured render in the table.
