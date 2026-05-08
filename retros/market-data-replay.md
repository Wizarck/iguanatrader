# Retrospective: market-data-replay

> **Forward-authored**.

- **PR**: TBD
- **Archive path**: `openspec/changes/archive/<archive-date>-market-data-replay/`
- **Lines shipped**: ~600 LoC (~250 src + ~280 tests + ~70 retro/openspec).

## What worked

- _(fill on archive — pre-flag candidates: optional `as_of` kwarg on `MarketDataPort.get_bars` keeps backwards-compatibility (existing daemon callers untouched); replay service is fully read-only by construction (no MessageBus injected, no broker dep); reuses existing `_make_strategy_resolver` from cli/trading.py for the strategy lookup; CLI subcommand auto-discovered into existing `iguanatrader market-data` Typer app from T4-followup-market-data.)_

## What didn't

- _(fill on archive — pre-flag candidates: `Proposal` dataclass has 11 fields incl. `confidence_score` + `mode` that I missed in the test fixture — caught at compile/lint time. Pre-flag for future tests touching trading.ports types.)_

## Carry-forward

- **Multi-day replay** (`--start-date / --end-date` looping) — operator scripts in shell for v1; native CLI loop is v2.
- **Persisted replay history** — stdout-only in v1; v2 SaaS slice can write to a `replay_history` table for ops dashboards.
- **Slippage / commission / equity simulation** — full backtest engine is a separate slice on the v1.5 backlog.
- **Proposal `reasoning` rendering**: cast to `str()` in v1 (dict serialisation); future improvement is a structured render in the table.
